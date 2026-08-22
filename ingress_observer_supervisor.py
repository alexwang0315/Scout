from __future__ import annotations

import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping


DEFAULT_SENSORLOGGER_ENV_FILE = Path("/data/scout/secrets/sensorlogger-mqtt.env")
DEFAULT_SENSORLOGGER_EVIDENCE_DIR = Path("/data/scout/admin/ingress/sensorlogger_mqtt")
DEFAULT_SENSORLOGGER_LOG_PATH = Path("/data/scout/admin/ingress/sensorlogger-mqtt-observer.log")
DEFAULT_GNSS_HARDWARE_EVIDENCE_DIR = Path("/data/scout/admin/ingress/gnss_hardware")
DEFAULT_GNSS_HARDWARE_LOG_PATH = Path("/data/scout/admin/ingress/gnss-hardware-observer.log")
DEFAULT_GNSS_HARDWARE_GATEWAY_JSONL = Path("/data/scout/providers/lora/sx1303-gateway-gps-nmea-smoke.jsonl")
DEFAULT_GNSS_HARDWARE_GROVE_JSONL = Path("/data/scout/providers/gnss/manual-smoke.jsonl")
DEFAULT_SX1303_GATEWAY_EVIDENCE_DIR = Path("/data/scout/admin/ingress/sx1303_gateway")
DEFAULT_SX1303_GATEWAY_LOG_PATH = Path("/data/scout/admin/ingress/sx1303-gateway-observer.log")
DEFAULT_SX1303_GATEWAY_UPLINK_JSONL = Path("/data/scout/providers/lora/sx1303-gateway-uplink.jsonl")
DEFAULT_SX1303_GATEWAY_GPS_JSONL = DEFAULT_GNSS_HARDWARE_GATEWAY_JSONL
DEFAULT_SX1303_GATEWAY_RF_PREFLIGHT_JSONL = Path("/data/scout/providers/lora/sx1303-gateway-smoke.jsonl")
DEFAULT_SX1303_GATEWAY_RX_READINESS_JSONL = Path("/data/scout/providers/lora/sx1303-gateway-rx-readiness.jsonl")
DEFAULT_SX1303_GATEWAY_CONFIG_PATHS = (
    "/data/scout/lora/global_conf.json,"
    "/data/scout/lora/station.conf,"
    "/data/scout/lora/chirpstack-gateway-bridge.toml,"
    "/data/scout/lora/chirpstack.toml,"
    "/data/scout/chirpstack/chirpstack.toml,"
    "/data/scout/chirpstack/regions/as923_2.toml,"
    "/data/scout/chirpstack/regions/as923.toml,"
    "/data/scout/providers/lora/chirpstack-docker/configuration/chirpstack/chirpstack.toml,"
    "/data/scout/providers/lora/chirpstack-docker/configuration/chirpstack/region_as923_2.toml,"
    "/data/scout/providers/lora/chirpstack-docker/configuration/chirpstack-gateway-bridge/"
    "chirpstack-gateway-bridge-basicstation-as923_2.toml"
)
DEFAULT_LORAWAN_CLIENT_EVIDENCE_DIR = Path("/data/scout/admin/ingress/lorawan_client")
DEFAULT_LORAWAN_CLIENT_LOG_PATH = Path("/data/scout/admin/ingress/lorawan-client-observer.log")
DEFAULT_LORAWAN_CLIENT_KEY_SYNC_JSONL = Path("/data/scout/providers/lora/wio-e5-chirpstack-key-sync.jsonl")
DEFAULT_LORAWAN_CLIENT_PROFILE_PROVISION_JSONL = Path("/data/scout/providers/lora/wio-e5-chirpstack-profile-provision.jsonl")
DEFAULT_LORAWAN_CLIENT_TRIAL_PLAN_JSONL = Path("/data/scout/providers/lora/wio-e5-uplink-trial-plan.jsonl")
DEFAULT_LORAWAN_CLIENT_RF_TRIAL_JSONL = Path("/data/scout/providers/lora/wio-e5-rf-trial.jsonl")
DEFAULT_LORAWAN_CLIENT_JOIN_AUDIT_JSONL = Path("/data/scout/providers/lora/wio-e5-chirpstack-join-audit.jsonl")
DEFAULT_LORAWAN_CLIENT_JOIN_STATE_DIAGNOSTIC_JSONL = Path(
    "/data/scout/providers/lora/wio-e5-chirpstack-join-state-diagnostic.jsonl"
)
DEFAULT_LORAWAN_CLIENT_UPLINK_JSONL = Path("/data/scout/providers/lora/sx1303-gateway-uplink.jsonl")
DEFAULT_LORAWAN_CLIENT_TAIL_STATUS_JSONL = Path("/data/scout/providers/lora/sx1303-gateway-uplink-tail-status.jsonl")
DEFAULT_LORAWAN_CLIENT_WIO_AT_JSONL = Path("/data/scout/providers/wio_e5/wio-e5-at-smoke.jsonl")
DEFAULT_PHYSIOLOGIC_GATE_EVIDENCE_DIR = Path("/data/scout/admin/ingress/physiologic_gate")
DEFAULT_PHYSIOLOGIC_GATE_LOG_PATH = Path("/data/scout/admin/ingress/physiologic-gate-observer.log")
DEFAULT_PHYSIOLOGIC_GATE_SENSORLOGGER_VITALS_JSONL = (
    DEFAULT_SENSORLOGGER_EVIDENCE_DIR / "sensorlogger_mqtt_sensor_vitals_records.jsonl"
)


PopenFactory = Callable[..., subprocess.Popen[Any]]


@dataclass(frozen=True)
class ObserverProcessSpec:
    name: str
    command: list[str]
    evidence_dir: Path
    status_path: Path
    log_path: Path
    env_file: Path | None = None
    autostart: bool = True
    reason: str | None = None


class IngressObserverSupervisor:
    def __init__(
        self,
        *,
        specs: list[ObserverProcessSpec],
        app_root: Path | str | None = None,
        enabled: bool = True,
        popen_factory: PopenFactory = subprocess.Popen,
    ) -> None:
        self.specs = list(specs)
        self.app_root = Path(app_root or Path(__file__).resolve().parent)
        self.enabled = enabled
        self._popen_factory = popen_factory
        self._processes: dict[str, subprocess.Popen[Any]] = {}
        self._started_at: dict[str, str] = {}
        self._last_error: dict[str, str] = {}

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str] | None = None,
        *,
        app_root: Path | str | None = None,
        popen_factory: PopenFactory = subprocess.Popen,
    ) -> "IngressObserverSupervisor":
        resolved_env = dict(env or os.environ)
        enabled = _is_true_like(
            resolved_env.get("SCOUT_INGRESS_OBSERVER_SUPERVISOR_ENABLED", "true")
        )
        specs: list[ObserverProcessSpec] = []
        sensorlogger = _sensorlogger_mqtt_spec(resolved_env, app_root=app_root)
        if sensorlogger is not None:
            specs.append(sensorlogger)
        gnss_hardware = _gnss_hardware_spec(resolved_env, app_root=app_root)
        if gnss_hardware is not None:
            specs.append(gnss_hardware)
        sx1303_gateway = _sx1303_gateway_spec(resolved_env, app_root=app_root)
        if sx1303_gateway is not None:
            specs.append(sx1303_gateway)
        lorawan_client = _lorawan_client_spec(resolved_env, app_root=app_root)
        if lorawan_client is not None:
            specs.append(lorawan_client)
        physiologic_gate = _physiologic_gate_spec(resolved_env, app_root=app_root)
        if physiologic_gate is not None:
            specs.append(physiologic_gate)
        return cls(
            specs=specs,
            app_root=app_root,
            enabled=enabled,
            popen_factory=popen_factory,
        )

    def start(self) -> None:
        if not self.enabled:
            return
        for spec in self.specs:
            if not spec.autostart:
                continue
            process = self._processes.get(spec.name)
            if process is not None and process.poll() is None:
                continue
            spec.log_path.parent.mkdir(parents=True, exist_ok=True)
            spec.evidence_dir.mkdir(parents=True, exist_ok=True)
            try:
                log_handle = spec.log_path.open("a", encoding="utf-8")
                try:
                    started_at = _now_label()
                    log_handle.write(f"\n[{started_at}] starting {spec.name}\n")
                    log_handle.flush()
                    self._processes[spec.name] = self._popen_factory(
                        spec.command,
                        cwd=str(self.app_root),
                        stdout=log_handle,
                        stderr=subprocess.STDOUT,
                    )
                    self._started_at[spec.name] = started_at
                    self._last_error.pop(spec.name, None)
                finally:
                    log_handle.close()
            except Exception as exc:
                self._last_error[spec.name] = f"{type(exc).__name__}:{exc}"

    def stop(self, *, timeout_seconds: float = 5.0) -> None:
        for name, process in list(self._processes.items()):
            if process.poll() is not None:
                continue
            process.terminate()
            deadline = time.monotonic() + timeout_seconds
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    break
                time.sleep(0.05)
            if process.poll() is None:
                process.kill()

    def status(self) -> dict[str, Any]:
        observers: list[dict[str, Any]] = []
        specs_by_name = {spec.name: spec for spec in self.specs}
        for spec in self.specs:
            process = self._processes.get(spec.name)
            returncode = process.poll() if process is not None else None
            observers.append(
                {
                    "name": spec.name,
                    "configured": True,
                    "autostart": spec.autostart,
                    "running": bool(process is not None and returncode is None),
                    "pid": process.pid if process is not None and returncode is None else None,
                    "returncode": returncode,
                    "started_at": self._started_at.get(spec.name),
                    "last_error": self._last_error.get(spec.name),
                    "status_path": str(spec.status_path),
                    "evidence_dir": str(spec.evidence_dir),
                    "log_path": str(spec.log_path),
                    "env_file": str(spec.env_file) if spec.env_file else None,
                    "env_file_exists": spec.env_file.exists() if spec.env_file else None,
                    "reason": spec.reason,
                    "credential_value_exposed": False,
                    "runtime_admission_performed": False,
                    "phase1_l0_l4_state_mutated": False,
                    "safety_api_called": False,
                    "phase2_brain_writeback": False,
                    "rf_tx_allowed": False,
                    "lorawan_uplink_allowed": False,
                    "downlink_allowed": False,
                }
            )
        return {
            "enabled": self.enabled,
            "observer_count": len(self.specs),
            "running_count": sum(1 for item in observers if item["running"]),
            "observers": observers,
            "configured_observer_names": sorted(specs_by_name),
            "boundary": {
                "read_only": True,
                "runtime_admission_performed": False,
                "phase1_l0_l4_state_mutated": False,
                "safety_api_called": False,
                "phase2_brain_writeback": False,
                "rf_tx_allowed": False,
                "lorawan_uplink_allowed": False,
                "downlink_allowed": False,
                "credential_value_exposed": False,
            },
        }


def _sensorlogger_mqtt_spec(
    env: Mapping[str, str],
    *,
    app_root: Path | str | None,
) -> ObserverProcessSpec | None:
    if not _is_true_like(env.get("SCOUT_SENSORLOGGER_MQTT_AUTOSTART", "true")):
        return None
    env_file = Path(
        env.get("SCOUT_SENSORLOGGER_MQTT_ENV_FILE", str(DEFAULT_SENSORLOGGER_ENV_FILE))
    ).expanduser()
    has_inline_config = bool(
        env.get("SCOUT_SENSORLOGGER_MQTT_HOST")
        and env.get("SCOUT_SENSORLOGGER_MQTT_TOPIC")
    )
    if not env_file.exists() and not has_inline_config:
        return None

    root = Path(app_root or Path(__file__).resolve().parent)
    observer_script = root / "scout_sensorlogger_mqtt_observer.py"
    evidence_dir = Path(
        env.get("SCOUT_SENSORLOGGER_MQTT_EVIDENCE_DIR", str(DEFAULT_SENSORLOGGER_EVIDENCE_DIR))
    ).expanduser()
    log_path = Path(
        env.get("SCOUT_SENSORLOGGER_MQTT_LOG_PATH", str(DEFAULT_SENSORLOGGER_LOG_PATH))
    ).expanduser()
    command = [
        sys.executable,
        str(observer_script),
        "--evidence-dir",
        str(evidence_dir),
        "--print-ready",
    ]
    reason = "env_file" if env_file.exists() else "inline_env"
    if env_file.exists():
        command.extend(["--env-file", str(env_file)])
    return ObserverProcessSpec(
        name="sensorlogger-mqtt",
        command=command,
        evidence_dir=evidence_dir,
        status_path=evidence_dir / "sensorlogger_mqtt_status.json",
        log_path=log_path,
        env_file=env_file if env_file.exists() else None,
        reason=reason,
    )


def _gnss_hardware_spec(
    env: Mapping[str, str],
    *,
    app_root: Path | str | None,
) -> ObserverProcessSpec | None:
    if not _is_true_like(env.get("SCOUT_GNSS_HARDWARE_AUTOSTART", "true")):
        return None

    gateway_jsonl = Path(
        env.get("SCOUT_GNSS_HARDWARE_GATEWAY_JSONL", str(DEFAULT_GNSS_HARDWARE_GATEWAY_JSONL))
    ).expanduser()
    grove_jsonl = Path(
        env.get("SCOUT_GNSS_HARDWARE_GROVE_JSONL", str(DEFAULT_GNSS_HARDWARE_GROVE_JSONL))
    ).expanduser()
    explicit_autostart = "SCOUT_GNSS_HARDWARE_AUTOSTART" in env
    explicit_source_config = any(
        key in env
        for key in (
            "SCOUT_GNSS_HARDWARE_GATEWAY_JSONL",
            "SCOUT_GNSS_HARDWARE_GROVE_JSONL",
            "SCOUT_GNSS_HARDWARE_EVIDENCE_DIR",
        )
    )
    force_autostart = _is_true_like(env.get("SCOUT_GNSS_HARDWARE_FORCE_AUTOSTART", "false"))
    if (
        not explicit_autostart
        and not explicit_source_config
        and not force_autostart
        and not gateway_jsonl.exists()
        and not grove_jsonl.exists()
    ):
        return None

    root = Path(app_root or Path(__file__).resolve().parent)
    observer_script = root / "scout_gnss_hardware_observer.py"
    evidence_dir = Path(
        env.get("SCOUT_GNSS_HARDWARE_EVIDENCE_DIR", str(DEFAULT_GNSS_HARDWARE_EVIDENCE_DIR))
    ).expanduser()
    log_path = Path(
        env.get("SCOUT_GNSS_HARDWARE_LOG_PATH", str(DEFAULT_GNSS_HARDWARE_LOG_PATH))
    ).expanduser()
    poll_seconds = env.get("SCOUT_GNSS_HARDWARE_POLL_SECONDS", "2.0")
    max_records = env.get("SCOUT_GNSS_HARDWARE_MAX_RECORDS", "200")
    command = [
        sys.executable,
        str(observer_script),
        "--evidence-dir",
        str(evidence_dir),
        "--gateway-jsonl",
        str(gateway_jsonl),
        "--grove-jsonl",
        str(grove_jsonl),
        "--poll-seconds",
        str(poll_seconds),
        "--max-records",
        str(max_records),
        "--print-ready",
    ]
    _append_gnss_hardware_display_args(command, env)
    if gateway_jsonl.exists() or grove_jsonl.exists():
        reason = "configured_sources"
    elif explicit_autostart or force_autostart:
        reason = "explicit_autostart"
    else:
        reason = "explicit_source_config"
    return ObserverProcessSpec(
        name="gnss-hardware",
        command=command,
        evidence_dir=evidence_dir,
        status_path=evidence_dir / "gnss_hardware_observer_status.json",
        log_path=log_path,
        reason=reason,
    )


def _append_gnss_hardware_display_args(command: list[str], env: Mapping[str, str]) -> None:
    if _is_true_like(env.get("SCOUT_GNSS_HARDWARE_OLED_STATUS")):
        command.append("--oled-status")
        _append_arg_from_env(command, "--oled-bus", env, "SCOUT_GNSS_HARDWARE_OLED_BUS")
        _append_arg_from_env(command, "--oled-address", env, "SCOUT_GNSS_HARDWARE_OLED_ADDRESS")
        _append_arg_from_env(command, "--oled-driver", env, "SCOUT_GNSS_HARDWARE_OLED_DRIVER")
    if _is_true_like(env.get("SCOUT_GNSS_HARDWARE_OLED_DRY_RUN")):
        command.append("--oled-dry-run")

    if _is_true_like(env.get("SCOUT_GNSS_HARDWARE_LED_STATUS")):
        command.append("--led-status")
        _append_arg_from_env(command, "--led-port", env, "SCOUT_GNSS_HARDWARE_LED_PORT")
        _append_arg_from_env(command, "--led-data-gpio", env, "SCOUT_GNSS_HARDWARE_LED_DATA_GPIO")
        _append_arg_from_env(command, "--led-clock-gpio", env, "SCOUT_GNSS_HARDWARE_LED_CLOCK_GPIO")
        _append_arg_from_env(command, "--led-fix-bit", env, "SCOUT_GNSS_HARDWARE_LED_FIX_BIT")
        _append_arg_from_env(command, "--led-no-fix-bit", env, "SCOUT_GNSS_HARDWARE_LED_NO_FIX_BIT")
        _append_arg_from_env(command, "--led-blink-count", env, "SCOUT_GNSS_HARDWARE_LED_BLINK_COUNT")
        _append_arg_from_env(command, "--led-blink-seconds", env, "SCOUT_GNSS_HARDWARE_LED_BLINK_SECONDS")
    if _is_true_like(env.get("SCOUT_GNSS_HARDWARE_LED_DRY_RUN")):
        command.append("--led-dry-run")


def _sx1303_gateway_spec(
    env: Mapping[str, str],
    *,
    app_root: Path | str | None,
) -> ObserverProcessSpec | None:
    explicit_autostart = "SCOUT_SX1303_GATEWAY_AUTOSTART" in env
    autostart_requested = _is_true_like(env.get("SCOUT_SX1303_GATEWAY_AUTOSTART", "false"))
    explicit_source_config = any(
        key in env
        for key in (
            "SCOUT_SX1303_GATEWAY_EVIDENCE_DIR",
            "SCOUT_SX1303_GATEWAY_UPLINK_JSONL",
            "SCOUT_SX1303_GATEWAY_GATEWAY_GPS_JSONL",
            "SCOUT_SX1303_GATEWAY_RF_PREFLIGHT_JSONL",
            "SCOUT_SX1303_GATEWAY_RX_READINESS_JSONL",
            "SCOUT_SX1303_GATEWAY_CONFIG_PATHS",
            "SCOUT_SX1303_GATEWAY_HOST",
        )
    )
    if not autostart_requested and not explicit_source_config:
        return None

    root = Path(app_root or Path(__file__).resolve().parent)
    observer_script = root / "scout_sx1303_gateway_observer.py"
    evidence_dir = Path(
        env.get("SCOUT_SX1303_GATEWAY_EVIDENCE_DIR", str(DEFAULT_SX1303_GATEWAY_EVIDENCE_DIR))
    ).expanduser()
    log_path = Path(
        env.get("SCOUT_SX1303_GATEWAY_LOG_PATH", str(DEFAULT_SX1303_GATEWAY_LOG_PATH))
    ).expanduser()
    uplink_jsonl = Path(
        env.get("SCOUT_SX1303_GATEWAY_UPLINK_JSONL", str(DEFAULT_SX1303_GATEWAY_UPLINK_JSONL))
    ).expanduser()
    gateway_gps_jsonl = Path(
        env.get("SCOUT_SX1303_GATEWAY_GATEWAY_GPS_JSONL", str(DEFAULT_SX1303_GATEWAY_GPS_JSONL))
    ).expanduser()
    rf_preflight_jsonl = Path(
        env.get("SCOUT_SX1303_GATEWAY_RF_PREFLIGHT_JSONL", str(DEFAULT_SX1303_GATEWAY_RF_PREFLIGHT_JSONL))
    ).expanduser()
    rx_readiness_jsonl = Path(
        env.get("SCOUT_SX1303_GATEWAY_RX_READINESS_JSONL", str(DEFAULT_SX1303_GATEWAY_RX_READINESS_JSONL))
    ).expanduser()
    command = [
        sys.executable,
        str(observer_script),
        "--evidence-dir",
        str(evidence_dir),
        "--uplink-jsonl",
        str(uplink_jsonl),
        "--gateway-gps-jsonl",
        str(gateway_gps_jsonl),
        "--rf-preflight-jsonl",
        str(rf_preflight_jsonl),
        "--rx-readiness-jsonl",
        str(rx_readiness_jsonl),
        "--config-paths",
        env.get("SCOUT_SX1303_GATEWAY_CONFIG_PATHS", DEFAULT_SX1303_GATEWAY_CONFIG_PATHS),
        "--expected-region-tokens",
        env.get("SCOUT_SX1303_GATEWAY_EXPECTED_REGION_TOKENS", "AS923,AS923_2,AS923_TW_920_925"),
        "--forbidden-region-tokens",
        env.get("SCOUT_SX1303_GATEWAY_FORBIDDEN_REGION_TOKENS", "EU868,US915,AU915,CN470,KR920,IN865,RU864"),
        "--host",
        env.get("SCOUT_SX1303_GATEWAY_HOST", "127.0.0.1"),
        "--tcp-ports",
        env.get("SCOUT_SX1303_GATEWAY_TCP_PORTS", "1883,3001,8080,8090"),
        "--udp-ports",
        env.get("SCOUT_SX1303_GATEWAY_UDP_PORTS", "1700"),
        "--poll-seconds",
        env.get("SCOUT_SX1303_GATEWAY_POLL_SECONDS", "10.0"),
        "--max-jsonl-records",
        env.get("SCOUT_SX1303_GATEWAY_MAX_JSONL_RECORDS", "200"),
        "--command-timeout-seconds",
        env.get("SCOUT_SX1303_GATEWAY_COMMAND_TIMEOUT_SECONDS", "2.0"),
        "--print-ready",
    ]
    _append_sx1303_gateway_display_args(command, env)
    reason = "explicit_autostart" if explicit_autostart and autostart_requested else "explicit_source_config"
    return ObserverProcessSpec(
        name="sx1303-gateway",
        command=command,
        evidence_dir=evidence_dir,
        status_path=evidence_dir / "sx1303_gateway_observer_status.json",
        log_path=log_path,
        reason=reason,
    )


def _append_sx1303_gateway_display_args(command: list[str], env: Mapping[str, str]) -> None:
    if _is_true_like(env.get("SCOUT_SX1303_GATEWAY_OLED_STATUS")):
        command.append("--oled-status")
        _append_arg_from_env(command, "--oled-bus", env, "SCOUT_SX1303_GATEWAY_OLED_BUS")
        _append_arg_from_env(command, "--oled-address", env, "SCOUT_SX1303_GATEWAY_OLED_ADDRESS")
        _append_arg_from_env(command, "--oled-driver", env, "SCOUT_SX1303_GATEWAY_OLED_DRIVER")
    if _is_true_like(env.get("SCOUT_SX1303_GATEWAY_OLED_DRY_RUN")):
        command.append("--oled-dry-run")

    if _is_true_like(env.get("SCOUT_SX1303_GATEWAY_LED_STATUS")):
        command.append("--led-status")
        _append_arg_from_env(command, "--led-port", env, "SCOUT_SX1303_GATEWAY_LED_PORT")
        _append_arg_from_env(command, "--led-data-gpio", env, "SCOUT_SX1303_GATEWAY_LED_DATA_GPIO")
        _append_arg_from_env(command, "--led-clock-gpio", env, "SCOUT_SX1303_GATEWAY_LED_CLOCK_GPIO")
        _append_arg_from_env(command, "--led-ok-bit", env, "SCOUT_SX1303_GATEWAY_LED_OK_BIT")
        _append_arg_from_env(command, "--led-warn-bit", env, "SCOUT_SX1303_GATEWAY_LED_WARN_BIT")
        _append_arg_from_env(command, "--led-fail-bit", env, "SCOUT_SX1303_GATEWAY_LED_FAIL_BIT")
        _append_arg_from_env(command, "--led-blink-count", env, "SCOUT_SX1303_GATEWAY_LED_BLINK_COUNT")
        _append_arg_from_env(command, "--led-blink-seconds", env, "SCOUT_SX1303_GATEWAY_LED_BLINK_SECONDS")
    if _is_true_like(env.get("SCOUT_SX1303_GATEWAY_LED_DRY_RUN")):
        command.append("--led-dry-run")


def _lorawan_client_spec(
    env: Mapping[str, str],
    *,
    app_root: Path | str | None,
) -> ObserverProcessSpec | None:
    explicit_autostart = "SCOUT_LORAWAN_CLIENT_AUTOSTART" in env
    autostart_requested = _is_true_like(env.get("SCOUT_LORAWAN_CLIENT_AUTOSTART", "false"))
    explicit_source_config = any(
        key in env
        for key in (
            "SCOUT_LORAWAN_CLIENT_EVIDENCE_DIR",
            "SCOUT_LORAWAN_CLIENT_KEY_SYNC_JSONL",
            "SCOUT_LORAWAN_CLIENT_PROFILE_PROVISION_JSONL",
            "SCOUT_LORAWAN_CLIENT_TRIAL_PLAN_JSONL",
            "SCOUT_LORAWAN_CLIENT_RF_TRIAL_JSONL",
            "SCOUT_LORAWAN_CLIENT_JOIN_AUDIT_JSONL",
            "SCOUT_LORAWAN_CLIENT_JOIN_STATE_DIAGNOSTIC_JSONL",
            "SCOUT_LORAWAN_CLIENT_UPLINK_JSONL",
            "SCOUT_LORAWAN_CLIENT_TAIL_STATUS_JSONL",
            "SCOUT_LORAWAN_CLIENT_WIO_AT_JSONL",
        )
    )
    default_sources = (
        DEFAULT_LORAWAN_CLIENT_KEY_SYNC_JSONL,
        DEFAULT_LORAWAN_CLIENT_PROFILE_PROVISION_JSONL,
        DEFAULT_LORAWAN_CLIENT_TRIAL_PLAN_JSONL,
        DEFAULT_LORAWAN_CLIENT_RF_TRIAL_JSONL,
        DEFAULT_LORAWAN_CLIENT_JOIN_AUDIT_JSONL,
        DEFAULT_LORAWAN_CLIENT_JOIN_STATE_DIAGNOSTIC_JSONL,
        DEFAULT_LORAWAN_CLIENT_UPLINK_JSONL,
        DEFAULT_LORAWAN_CLIENT_TAIL_STATUS_JSONL,
        DEFAULT_LORAWAN_CLIENT_WIO_AT_JSONL,
    )
    if not autostart_requested and not explicit_source_config and not any(path.exists() for path in default_sources):
        return None

    root = Path(app_root or Path(__file__).resolve().parent)
    observer_script = root / "scout_lorawan_client_observer.py"
    evidence_dir = Path(
        env.get("SCOUT_LORAWAN_CLIENT_EVIDENCE_DIR", str(DEFAULT_LORAWAN_CLIENT_EVIDENCE_DIR))
    ).expanduser()
    log_path = Path(env.get("SCOUT_LORAWAN_CLIENT_LOG_PATH", str(DEFAULT_LORAWAN_CLIENT_LOG_PATH))).expanduser()
    command = [
        sys.executable,
        str(observer_script),
        "--evidence-dir",
        str(evidence_dir),
        "--key-sync-jsonl",
        env.get("SCOUT_LORAWAN_CLIENT_KEY_SYNC_JSONL", str(DEFAULT_LORAWAN_CLIENT_KEY_SYNC_JSONL)),
        "--profile-provision-jsonl",
        env.get(
            "SCOUT_LORAWAN_CLIENT_PROFILE_PROVISION_JSONL",
            str(DEFAULT_LORAWAN_CLIENT_PROFILE_PROVISION_JSONL),
        ),
        "--trial-plan-jsonl",
        env.get("SCOUT_LORAWAN_CLIENT_TRIAL_PLAN_JSONL", str(DEFAULT_LORAWAN_CLIENT_TRIAL_PLAN_JSONL)),
        "--rf-trial-jsonl",
        env.get("SCOUT_LORAWAN_CLIENT_RF_TRIAL_JSONL", str(DEFAULT_LORAWAN_CLIENT_RF_TRIAL_JSONL)),
        "--join-audit-jsonl",
        env.get("SCOUT_LORAWAN_CLIENT_JOIN_AUDIT_JSONL", str(DEFAULT_LORAWAN_CLIENT_JOIN_AUDIT_JSONL)),
        "--join-state-diagnostic-jsonl",
        env.get(
            "SCOUT_LORAWAN_CLIENT_JOIN_STATE_DIAGNOSTIC_JSONL",
            str(DEFAULT_LORAWAN_CLIENT_JOIN_STATE_DIAGNOSTIC_JSONL),
        ),
        "--uplink-jsonl",
        env.get("SCOUT_LORAWAN_CLIENT_UPLINK_JSONL", str(DEFAULT_LORAWAN_CLIENT_UPLINK_JSONL)),
        "--tail-status-jsonl",
        env.get("SCOUT_LORAWAN_CLIENT_TAIL_STATUS_JSONL", str(DEFAULT_LORAWAN_CLIENT_TAIL_STATUS_JSONL)),
        "--wio-at-jsonl",
        env.get("SCOUT_LORAWAN_CLIENT_WIO_AT_JSONL", str(DEFAULT_LORAWAN_CLIENT_WIO_AT_JSONL)),
        "--poll-seconds",
        env.get("SCOUT_LORAWAN_CLIENT_POLL_SECONDS", "10.0"),
        "--max-jsonl-records",
        env.get("SCOUT_LORAWAN_CLIENT_MAX_JSONL_RECORDS", "200"),
        "--print-ready",
    ]
    _append_lorawan_client_display_args(command, env)
    if explicit_autostart and autostart_requested:
        reason = "explicit_autostart"
    elif explicit_source_config:
        reason = "explicit_source_config"
    else:
        reason = "configured_sources"
    return ObserverProcessSpec(
        name="lorawan-client",
        command=command,
        evidence_dir=evidence_dir,
        status_path=evidence_dir / "lorawan_client_observer_status.json",
        log_path=log_path,
        reason=reason,
    )


def _append_lorawan_client_display_args(command: list[str], env: Mapping[str, str]) -> None:
    if _is_true_like(env.get("SCOUT_LORAWAN_CLIENT_OLED_STATUS")):
        command.append("--oled-status")
        _append_arg_from_env(command, "--oled-bus", env, "SCOUT_LORAWAN_CLIENT_OLED_BUS")
        _append_arg_from_env(command, "--oled-address", env, "SCOUT_LORAWAN_CLIENT_OLED_ADDRESS")
        _append_arg_from_env(command, "--oled-driver", env, "SCOUT_LORAWAN_CLIENT_OLED_DRIVER")
    if _is_true_like(env.get("SCOUT_LORAWAN_CLIENT_OLED_DRY_RUN")):
        command.append("--oled-dry-run")

    if _is_true_like(env.get("SCOUT_LORAWAN_CLIENT_LED_STATUS")):
        command.append("--led-status")
        _append_arg_from_env(command, "--led-port", env, "SCOUT_LORAWAN_CLIENT_LED_PORT")
        _append_arg_from_env(command, "--led-data-gpio", env, "SCOUT_LORAWAN_CLIENT_LED_DATA_GPIO")
        _append_arg_from_env(command, "--led-clock-gpio", env, "SCOUT_LORAWAN_CLIENT_LED_CLOCK_GPIO")
        _append_arg_from_env(command, "--led-ok-bit", env, "SCOUT_LORAWAN_CLIENT_LED_OK_BIT")
        _append_arg_from_env(command, "--led-warn-bit", env, "SCOUT_LORAWAN_CLIENT_LED_WARN_BIT")
        _append_arg_from_env(command, "--led-fail-bit", env, "SCOUT_LORAWAN_CLIENT_LED_FAIL_BIT")
        _append_arg_from_env(command, "--led-blink-count", env, "SCOUT_LORAWAN_CLIENT_LED_BLINK_COUNT")
        _append_arg_from_env(command, "--led-blink-seconds", env, "SCOUT_LORAWAN_CLIENT_LED_BLINK_SECONDS")
    if _is_true_like(env.get("SCOUT_LORAWAN_CLIENT_LED_DRY_RUN")):
        command.append("--led-dry-run")


def _physiologic_gate_spec(
    env: Mapping[str, str],
    *,
    app_root: Path | str | None,
) -> ObserverProcessSpec | None:
    explicit_autostart = "SCOUT_PHYSIOLOGIC_GATE_AUTOSTART" in env
    autostart_requested = _is_true_like(env.get("SCOUT_PHYSIOLOGIC_GATE_AUTOSTART", "false"))
    explicit_source_config = any(
        key in env
        for key in (
            "SCOUT_PHYSIOLOGIC_GATE_SENSORLOGGER_VITALS_JSONL",
            "SCOUT_PHYSIOLOGIC_GATE_BASELINE_JSON",
            "SCOUT_PHYSIOLOGIC_GATE_ROUTE_CONTEXT_JSON",
            "SCOUT_PHYSIOLOGIC_GATE_EVIDENCE_DIR",
        )
    )
    if not autostart_requested and not explicit_source_config:
        return None

    sensorlogger_vitals_jsonl = Path(
        env.get(
            "SCOUT_PHYSIOLOGIC_GATE_SENSORLOGGER_VITALS_JSONL",
            str(DEFAULT_PHYSIOLOGIC_GATE_SENSORLOGGER_VITALS_JSONL),
        )
    ).expanduser()
    root = Path(app_root or Path(__file__).resolve().parent)
    observer_script = root / "scout_physiologic_gate_observer.py"
    evidence_dir = Path(
        env.get("SCOUT_PHYSIOLOGIC_GATE_EVIDENCE_DIR", str(DEFAULT_PHYSIOLOGIC_GATE_EVIDENCE_DIR))
    ).expanduser()
    log_path = Path(
        env.get("SCOUT_PHYSIOLOGIC_GATE_LOG_PATH", str(DEFAULT_PHYSIOLOGIC_GATE_LOG_PATH))
    ).expanduser()
    poll_seconds = env.get("SCOUT_PHYSIOLOGIC_GATE_POLL_SECONDS", "30.0")
    window_minutes = env.get("SCOUT_PHYSIOLOGIC_GATE_WINDOW_MINUTES", "15")
    max_records = env.get("SCOUT_PHYSIOLOGIC_GATE_MAX_RECORDS", "1000")
    command = [
        sys.executable,
        str(observer_script),
        "--sensorlogger-vitals-jsonl",
        str(sensorlogger_vitals_jsonl),
        "--evidence-dir",
        str(evidence_dir),
        "--poll-seconds",
        str(poll_seconds),
        "--window-minutes",
        str(window_minutes),
        "--max-records",
        str(max_records),
        "--print-ready",
    ]
    _append_arg_from_env(command, "--baseline-json", env, "SCOUT_PHYSIOLOGIC_GATE_BASELINE_JSON")
    _append_arg_from_env(command, "--route-context-json", env, "SCOUT_PHYSIOLOGIC_GATE_ROUTE_CONTEXT_JSON")
    _append_arg_from_env(command, "--activity-type", env, "SCOUT_PHYSIOLOGIC_GATE_ACTIVITY_TYPE")
    reason = "explicit_autostart" if explicit_autostart and autostart_requested else "explicit_source_config"
    return ObserverProcessSpec(
        name="physiologic-gate",
        command=command,
        evidence_dir=evidence_dir,
        status_path=evidence_dir / "physiologic_gate_status.json",
        log_path=log_path,
        reason=reason,
    )


def _append_arg_from_env(command: list[str], option: str, env: Mapping[str, str], env_key: str) -> None:
    value = env.get(env_key)
    if value in (None, ""):
        return
    command.extend([option, value])


def _is_true_like(value: str | None) -> bool:
    return value is not None and value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _now_label() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
