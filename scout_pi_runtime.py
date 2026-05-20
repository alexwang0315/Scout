from __future__ import annotations

import json
import os
import platform
from collections.abc import Mapping
from hmac import compare_digest
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from assistant_api import (
    create_assistant_provider_from_env,
    create_assistant_provider_status,
    create_assistant_router,
)
from incident_store import IncidentStore
from live_runtime_enablement import (
    LiveRuntimeGate,
    build_live_runtime_enablement_report,
    load_hardware_provider_control_policy,
)
from runtime_stream_controls import RuntimeStreamControlStore
from runtime_stream_status_surface import create_runtime_stream_status_router
from runtime_stream_telemetry import RuntimeStreamTelemetryStore
from runtime_stream_transport_api import create_runtime_stream_transport_router
from safety_api import SafetyApiSnapshot, create_safety_router
from safety_models import SafetyState
from safety_runtime_session import SafetyRuntimeSession
from server_safety_observation_admission_config import (
    create_safety_observation_admission_config_from_env,
)


ROOT = Path(__file__).resolve().parent
DEFAULT_DATA_ROOT = Path.home() / ".scout-fusion" / "pi-runtime"
DEFAULT_MISSION_GRAPH = ROOT / "tests" / "fixtures" / "mission_graph" / "normal_climb_mission.json"
REQUIRED_DATA_DIRECTORIES = ("missions", "incidents", "capsules", "raw_ring", "logs", "providers", "tmp")


class HardwareProviderControlRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operator_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)


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
    live_runtime_enabled = _is_true_like(env.get("SCOUT_ENABLE_LIVE_RUNTIME"))
    remote_provider_live_send_enabled = _is_true_like(
        env.get("SCOUT_REMOTE_PROVIDER_LIVE_SEND_ENABLED")
    )
    hardware_provider_control_enabled = _is_true_like(
        env.get("SCOUT_HARDWARE_PROVIDER_CONTROL_ENABLED")
    ) or live_hardware_enabled
    ai_fallback_mode = env.get("SCOUT_AI_FALLBACK_MODE", "offline_only")
    event_bus = env.get("SCOUT_EVENT_BUS", "none")
    runtime_stream_status_enabled = _is_true_like(
        env.get("SCOUT_RUNTIME_STREAM_STATUS_ENABLED")
    )
    live_enablement_report = (
        build_live_runtime_enablement_report(env, requested_gates=set(LiveRuntimeGate))
        if live_runtime_enabled
        else None
    )
    live_enablement_ready = bool(
        live_enablement_report and live_enablement_report.ready
    )
    step1_blockers = (
        []
        if live_runtime_enabled
        else _step1_blockers(
            live_hardware_enabled=live_hardware_enabled,
            ai_inference_enabled=ai_inference_enabled,
            local_model_enabled=local_model_enabled,
            event_bus=event_bus,
        )
    )

    _ensure_data_root(data_root)
    incident_store = IncidentStore(incident_store_path)

    runtime_session: SafetyRuntimeSession | None = None
    runtime_error: str | None = None
    observation_admission_config = None
    observation_admission_error: str | None = None
    if _is_true_like(env.get("SCOUT_SAFETY_OBSERVATION_ADMISSION_ENABLED")):
        try:
            observation_admission_config = create_safety_observation_admission_config_from_env(env)
        except Exception as exc:
            observation_admission_error = f"{type(exc).__name__}: {exc}"
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
            observation_admission_config=observation_admission_config,
        )
    )
    telemetry_store = RuntimeStreamTelemetryStore()
    control_store = RuntimeStreamControlStore()
    runtime_stream_transport_enabled = (
        live_enablement_ready
        and runtime_session is not None
        and observation_admission_config is not None
        and LiveRuntimeGate.RUNTIME_STREAM.value in live_enablement_report.ready_gates
    )
    if runtime_stream_status_enabled:
        app.include_router(
            create_runtime_stream_status_router(
                telemetry_store=telemetry_store,
                control_store=control_store,
                admission_state=(
                    observation_admission_config.state
                    if observation_admission_config is not None
                    else None
                ),
                transport_routes_mounted=runtime_stream_transport_enabled,
                live_provider_send_allowed=(
                    remote_provider_live_send_enabled and live_enablement_ready
                ),
            )
        )
    if runtime_stream_transport_enabled:
        app.include_router(
            create_runtime_stream_transport_router(
                runtime_session=runtime_session,
                observation_admission_config=observation_admission_config,
                telemetry_store=telemetry_store,
                control_store=control_store,
            )
        )
    if live_enablement_ready and _is_true_like(env.get("SCOUT_AI_ASSISTANT_ENABLED")):
        provider = create_assistant_provider_from_env(dict(env))
        app.include_router(
            create_assistant_router(
                provider=provider,
                provider_status=create_assistant_provider_status(
                    provider=provider,
                    environ=dict(env),
                ),
            )
        )
    hardware_control_policy = (
        load_hardware_provider_control_policy(
            env["SCOUT_HARDWARE_PROVIDER_CONTROL_POLICY_PATH"]
        )
        if live_enablement_ready
        and LiveRuntimeGate.HARDWARE_PROVIDER_CONTROL.value
        in live_enablement_report.ready_gates
        else None
    )
    if hardware_control_policy is not None:
        _include_hardware_provider_control_routes(
            app,
            data_root=data_root,
            policy=hardware_control_policy,
            bearer_token=_hardware_control_token_from_env(env),
        )

    @app.get("/health")
    def health(response: Response) -> dict[str, Any]:
        storage = _storage_status(data_root, incident_store_path)
        live_blockers = (
            live_enablement_report.blocker_reasons
            if live_enablement_report is not None and not live_enablement_report.ready
            else []
        )
        ok = (
            runtime_session is not None
            and storage["data_root_writable"]
            and not step1_blockers
            and not live_blockers
            and observation_admission_error is None
        )
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
            "live_enablement": (
                live_enablement_report.model_dump(mode="json")
                if live_enablement_report is not None
                else None
            ),
            "observation_admission_error": observation_admission_error,
            "optional_features": {
                "live_runtime_enabled": live_runtime_enabled,
                "live_hardware_enabled": live_hardware_enabled,
                "ai_inference_enabled": ai_inference_enabled,
                "local_model_enabled": local_model_enabled,
                "ai_fallback_mode": ai_fallback_mode,
                "event_bus": event_bus,
                "runtime_stream_status_enabled": runtime_stream_status_enabled,
                "runtime_stream_transport_enabled": runtime_stream_transport_enabled,
                "remote_provider_live_send_enabled": (
                    remote_provider_live_send_enabled and live_enablement_ready
                ),
                "hardware_provider_control_enabled": (
                    hardware_control_policy is not None
                    and hardware_provider_control_enabled
                ),
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
            "runtime_stream_status_enabled": runtime_stream_status_enabled,
            "runtime_stream_transport_enabled": runtime_stream_transport_enabled,
            "step1_blockers": step1_blockers,
            "live_enablement_status": (
                live_enablement_report.status.value
                if live_enablement_report is not None
                else None
            ),
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
            "provider_contract": (
                "live_control_policy"
                if hardware_control_policy is not None and hardware_provider_control_enabled
                else "fixture_or_degraded_step1"
            ),
            "providers": [
                {
                    "provider_id": (
                        hardware_control_policy.allowed_provider_refs[0]
                        if hardware_control_policy is not None
                        else "gnss.position"
                    ),
                    "mode": "live_control_policy" if hardware_control_policy is not None else "fixture",
                    "status": "ready" if runtime_session is not None else "unavailable",
                    "evidence": "normalized observation payload",
                    "control_allowed": hardware_control_policy is not None,
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


def _include_hardware_provider_control_routes(
    app: FastAPI,
    *,
    data_root: Path,
    policy: Any,
    bearer_token: str,
) -> None:
    @app.get("/providers/control/status")
    def hardware_provider_control_status() -> dict[str, Any]:
        return {
            "artifact_kind": "hardware_provider_control_status",
            "status": "enabled",
            "policy_id": policy.policy_id,
            "allowed_provider_refs": list(policy.allowed_provider_refs),
            "allowed_actions": [action.value for action in policy.allowed_actions],
            "operator_authorization_required": True,
            "token_value_exposed": False,
            "safety_mutation_allowed": False,
            "outbound_send_allowed": False,
        }

    @app.post("/providers/control/{provider_ref}/actions/{action}")
    def hardware_provider_control_action(
        provider_ref: str,
        action: str,
        request: HardwareProviderControlRequest,
        http_request: Request,
    ) -> dict[str, Any]:
        if not _bearer_token_valid(
            http_request.headers.get("authorization", ""),
            bearer_token,
        ):
            raise HTTPException(status_code=401, detail={"reason": "hardware_control_auth_required"})
        if provider_ref not in policy.allowed_provider_refs:
            raise HTTPException(status_code=403, detail={"reason": "provider_ref_not_allowed"})
        allowed_actions = [item.value for item in policy.allowed_actions]
        if action not in allowed_actions:
            raise HTTPException(status_code=403, detail={"reason": "action_not_allowed"})
        record = {
            "artifact_kind": "hardware_provider_control_record",
            "status": "control_command_recorded",
            "provider_ref": provider_ref,
            "action": action,
            "operator_id": request.operator_id,
            "reason": request.reason,
            "provider_control_authorized": True,
            "hardware_driver_invoked": False,
            "safety_mutation_allowed": False,
            "outbound_send_allowed": False,
            "token_value_exposed": False,
        }
        control_log = data_root / "providers" / "hardware-control-records.jsonl"
        control_log.parent.mkdir(parents=True, exist_ok=True)
        with control_log.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        return record


def _bearer_token_valid(header: str, token: str) -> bool:
    prefix = "Bearer "
    if not header.startswith(prefix) or not token:
        return False
    return compare_digest(header.removeprefix(prefix).strip(), token)


def _hardware_control_token_from_env(env: Mapping[str, str]) -> str:
    token = env.get("SCOUT_HARDWARE_PROVIDER_CONTROL_TOKEN", "").strip()
    if token:
        return token
    token_file = env.get("SCOUT_HARDWARE_PROVIDER_CONTROL_TOKEN_FILE", "").strip()
    if not token_file:
        return ""
    try:
        return Path(token_file).expanduser().read_text(encoding="utf-8").strip()
    except OSError:
        return ""


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
