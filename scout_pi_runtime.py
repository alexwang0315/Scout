from __future__ import annotations

import os
import platform
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Response

from incident_store import IncidentStore
from safety_api import SafetyApiSnapshot, create_safety_router
from safety_models import SafetyState
from safety_runtime_session import SafetyRuntimeSession


ROOT = Path(__file__).resolve().parent
DEFAULT_DATA_ROOT = Path.home() / ".scout-fusion" / "pi-runtime"
DEFAULT_MISSION_GRAPH = ROOT / "tests" / "fixtures" / "mission_graph" / "normal_climb_mission.json"
REQUIRED_DATA_DIRECTORIES = ("missions", "incidents", "capsules", "raw_ring", "logs", "providers", "tmp")


def create_pi_runtime_app(environ: Mapping[str, str] | None = None) -> FastAPI:
    env = environ or os.environ
    data_root = _path_from_env(env, "SCOUT_DATA_ROOT", DEFAULT_DATA_ROOT)
    incident_store_path = _path_from_env(
        env,
        "SCOUT_SAFETY_INCIDENT_STORE",
        data_root / "incidents",
    )
    mission_graph_path = _path_from_env(
        env,
        "SCOUT_SAFETY_MISSION_GRAPH",
        DEFAULT_MISSION_GRAPH,
    )
    route_progress_config_path = _optional_path_from_env(
        env,
        "SCOUT_SAFETY_ROUTE_PROGRESS_CONFIG",
    )
    runtime_profile = env.get("SCOUT_RUNTIME_PROFILE", "pi-field")
    live_hardware_enabled = _is_true_like(env.get("SCOUT_ENABLE_LIVE_HARDWARE"))
    ai_inference_enabled = _is_true_like(env.get("SCOUT_ENABLE_AI_INFERENCE"))
    local_model_enabled = _is_true_like(env.get("SCOUT_ENABLE_LOCAL_MODEL"))
    ai_fallback_mode = env.get("SCOUT_AI_FALLBACK_MODE", "offline_only")
    event_bus = env.get("SCOUT_EVENT_BUS", "none")
    step1_blockers = _step1_blockers(
        live_hardware_enabled=live_hardware_enabled,
        ai_inference_enabled=ai_inference_enabled,
        local_model_enabled=local_model_enabled,
        event_bus=event_bus,
    )

    _ensure_data_root(data_root)
    incident_store = IncidentStore(incident_store_path)

    runtime_session: SafetyRuntimeSession | None = None
    runtime_error: str | None = None
    if _is_true_like(env.get("SCOUT_SAFETY_ENABLED", "true")):
        try:
            runtime_session = SafetyRuntimeSession(
                mission_graph_path,
                route_progress_config_path=route_progress_config_path,
                incident_store_path=incident_store_path,
            )
        except Exception as exc:  # pragma: no cover - surfaced by health endpoint
            runtime_error = f"{type(exc).__name__}: {exc}"
    else:
        runtime_error = "safety runtime disabled by SCOUT_SAFETY_ENABLED"

    app = FastAPI(
        title="Scout Pi Runtime",
        description="Minimal Scout deterministic field runtime for Raspberry Pi deployment.",
        version="0.1.0",
    )
    app.include_router(
        create_safety_router(
            SafetyApiSnapshot(safety_state=SafetyState()),
            incident_store=incident_store,
            runtime_session=runtime_session,
        )
    )

    @app.get("/health")
    def health(response: Response) -> dict[str, Any]:
        storage = _storage_status(data_root, incident_store_path)
        ok = runtime_session is not None and storage["data_root_writable"] and not step1_blockers
        if not ok:
            response.status_code = 503
        return {
            "status": "ok" if ok else "degraded",
            "runtime_profile": runtime_profile,
            "machine": platform.machine(),
            "data_root": str(data_root),
            "incident_store": str(incident_store_path),
            "mission_graph": str(mission_graph_path),
            "safety_runtime": {
                "enabled": runtime_session is not None,
                "error": runtime_error,
            },
            "storage": storage,
            "step1_blockers": step1_blockers,
            "optional_features": {
                "live_hardware_enabled": live_hardware_enabled,
                "ai_inference_enabled": ai_inference_enabled,
                "local_model_enabled": local_model_enabled,
                "ai_fallback_mode": ai_fallback_mode,
                "event_bus": event_bus,
            },
        }

    @app.get("/runtime/status")
    def runtime_status() -> dict[str, Any]:
        snapshot = runtime_session.snapshot() if runtime_session is not None else None
        return {
            "runtime_profile": runtime_profile,
            "data_root": str(data_root),
            "safety_runtime_enabled": runtime_session is not None,
            "runtime_error": runtime_error,
            "mission_graph": str(mission_graph_path),
            "incident_store": str(incident_store_path),
            "event_bus": event_bus,
            "step1_blockers": step1_blockers,
            "observations_processed": snapshot.observations_processed if snapshot else 0,
            "safety_level": snapshot.safety_state.level if snapshot else SafetyState().level,
            "checkpoint_hits": len(snapshot.checkpoint_hits) if snapshot else 0,
            "segment_capsules": len(snapshot.segment_capsules) if snapshot else 0,
            "incident_packages": len(snapshot.incident_packages) if snapshot else 0,
            "stored_incidents": len(incident_store.list_ids()),
        }

    @app.get("/providers/status")
    def providers_status() -> dict[str, Any]:
        return {
            "live_hardware_enabled": live_hardware_enabled,
            "provider_contract": "fixture_or_degraded_step1",
            "providers": [
                {
                    "provider_id": "gnss.position",
                    "mode": "fixture",
                    "status": "ready" if runtime_session is not None else "unavailable",
                    "evidence": "normalized observation payload",
                    "control_allowed": False,
                },
                {
                    "provider_id": "imu.motion",
                    "mode": "fixture",
                    "status": "ready" if runtime_session is not None else "unavailable",
                    "evidence": "normalized observation payload",
                    "control_allowed": False,
                },
                {
                    "provider_id": "battery.status",
                    "mode": "fixture",
                    "status": "ready" if runtime_session is not None else "unavailable",
                    "evidence": "normalized observation payload",
                    "control_allowed": False,
                },
                {
                    "provider_id": "communication.status",
                    "mode": "fixture",
                    "status": "ready" if runtime_session is not None else "unavailable",
                    "evidence": "server_signal_snapshot or unavailable_by_platform",
                    "control_allowed": False,
                },
            ],
        }

    return app


def _path_from_env(env: Mapping[str, str], key: str, default: Path) -> Path:
    raw_value = env.get(key)
    return Path(raw_value).expanduser() if raw_value else default


def _optional_path_from_env(env: Mapping[str, str], key: str) -> Path | None:
    raw_value = env.get(key)
    return Path(raw_value).expanduser() if raw_value else None


def _is_true_like(value: str | None) -> bool:
    return value is not None and value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _ensure_data_root(data_root: Path) -> None:
    for child in REQUIRED_DATA_DIRECTORIES:
        (data_root / child).mkdir(parents=True, exist_ok=True)


def _storage_status(data_root: Path, incident_store_path: Path) -> dict[str, Any]:
    missing_directories = [
        child for child in REQUIRED_DATA_DIRECTORIES if not (data_root / child).is_dir()
    ]
    return {
        "data_root_exists": data_root.exists(),
        "data_root_writable": _is_writable(data_root),
        "incident_store_exists": incident_store_path.exists(),
        "incident_store_writable": _is_writable(incident_store_path),
        "required_directories": list(REQUIRED_DATA_DIRECTORIES),
        "missing_directories": missing_directories,
    }


def _is_writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".scout_write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError:
        return False
    return True


def _step1_blockers(
    *,
    live_hardware_enabled: bool,
    ai_inference_enabled: bool,
    local_model_enabled: bool,
    event_bus: str,
) -> list[str]:
    blockers: list[str] = []
    if live_hardware_enabled:
        blockers.append("live_hardware_must_stay_disabled_for_step1")
    if ai_inference_enabled:
        blockers.append("ai_inference_must_stay_disabled_for_step1")
    if local_model_enabled:
        blockers.append("local_model_must_stay_disabled_for_step1")
    if event_bus != "none":
        blockers.append("event_bus_must_stay_none_for_step1")
    return blockers


app = create_pi_runtime_app()
