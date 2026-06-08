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


def _is_true_like(value: str | None) -> bool:
    return value is not None and value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _now_label() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
