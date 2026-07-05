from __future__ import annotations

import os
from base64 import b64decode
from contextlib import asynccontextmanager
from hmac import compare_digest
from pathlib import Path
from typing import Any, Mapping

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from admin_api import create_admin_router
from assistant_api import (
    answer_assistant_query_safely,
    create_assistant_context_registry_status,
    create_assistant_provider_from_env,
    create_assistant_provider_status,
)
from assistant_context import (
    augment_sources_with_configured_live_navigation_evidence,
    assistant_source_refs_from_context,
    create_assistant_context_resolver,
    query_source_refs,
)
from assistant_models import AssistantSourceRef, AssistantSurface, ScoutAssistantQuery, ScoutAssistantResponse
from assistant_skill_router import augment_pretrip_sources_with_local_evidence_search
from debug_api import create_debug_page_router, create_debug_router
from hardware_readiness_api import create_hardware_readiness_router
from ingress_observer_supervisor import IngressObserverSupervisor
from pretrip_assistant_context import build_pretrip_assistant_context
from runtime_debug_log import FileRuntimeDebugEventLog
from scout_env import load_scout_env_files


DEFAULT_DATA_ROOT = Path("/data/scout")
DEFAULT_ADMIN_WORKSPACE_ROOT = DEFAULT_DATA_ROOT / "admin" / "pretrip-workspaces"
DEFAULT_INCIDENT_STORE = DEFAULT_DATA_ROOT / "incidents"
DEFAULT_ADMIN_BASIC_USERNAME = "scout-admin"


def create_phase4_admin_runtime_app(
    *,
    environ: Mapping[str, str] | None = None,
) -> FastAPI:
    if environ is None:
        load_scout_env_files(repo_root=Path(__file__).resolve().parent)
    env = dict(environ or os.environ)
    data_root = Path(env.get("SCOUT_DATA_ROOT", str(DEFAULT_DATA_ROOT))).expanduser()
    workspace_root = Path(
        env.get("SCOUT_PRETRIP_WORKSPACE_ROOT", str(DEFAULT_ADMIN_WORKSPACE_ROOT))
    ).expanduser()
    incident_store = Path(
        env.get("SCOUT_SAFETY_INCIDENT_STORE", str(DEFAULT_INCIDENT_STORE))
    ).expanduser()
    assistant_enabled = _is_true_like(env.get("SCOUT_AI_ASSISTANT_ENABLED", "1"))
    debug_enabled = _is_true_like(env.get("SCOUT_DEBUG_API_ENABLED"))
    debug_log_path = env.get("SCOUT_DEBUG_LOG_PATH")
    agent_trace_log_path = env.get("SCOUT_AGENT_TRACE_LOG_PATH")
    mobile_wearable_ingress_status_path = _mobile_wearable_ingress_status_path(env)
    spatial_imprint_store_path = env.get("SCOUT_SPATIAL_IMPRINT_STORE_PATH")
    spatial_imprint_trigger_report_path = env.get("SCOUT_SPATIAL_IMPRINT_TRIGGER_REPORT_PATH")
    hardware_readiness_fixture_path = env.get("SCOUT_HARDWARE_READINESS_FIXTURE_PATH")
    auth_config = _admin_auth_config(env)
    provider = create_assistant_provider_from_env(env)
    ingress_observer_supervisor = IngressObserverSupervisor.from_env(env)
    live_navigation_evidence_dir = _optional_path(
        env.get("SCOUT_SENSORLOGGER_MQTT_EVIDENCE_DIR")
    )
    assistant_context_registry_status = create_assistant_context_registry_status(
        environ=env,
        pretrip_workspace_root=workspace_root,
        live_navigation_evidence_dir=live_navigation_evidence_dir,
    )
    provider_status = create_assistant_provider_status(provider=provider, environ=env)
    provider_status["assistant_context_registry"] = assistant_context_registry_status
    assistant_context_resolver = create_assistant_context_resolver(
        pretrip_workspace_root=workspace_root,
        live_navigation_evidence_dir=live_navigation_evidence_dir,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        ingress_observer_supervisor.start()
        try:
            yield
        finally:
            ingress_observer_supervisor.stop()

    app = FastAPI(
        title="Scout Phase 4 Admin LAN Preview",
        description=(
            "LAN-visible Phase 4 admin preview for Scout hardware. This app exposes "
            "planning/admin surfaces only and does not run the Phase 1 field runtime."
        ),
        version="0.1.0",
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def admin_auth_middleware(request: Request, call_next):
        if _admin_auth_allowed(request, auth_config):
            return await call_next(request)
        status_code = 503 if auth_config["misconfigured"] else 401
        headers = {}
        if status_code == 401:
            headers["WWW-Authenticate"] = (
                f'Basic realm="Scout Phase 4 Admin", charset="UTF-8"'
            )
        return JSONResponse(
            {
                "detail": (
                    "admin auth is required"
                    if status_code == 401
                    else "admin auth is required but no token is configured"
                ),
                "auth": _admin_auth_status(auth_config),
            },
            status_code=status_code,
            headers=headers,
        )

    app.include_router(
        create_admin_router(
            incident_store_path=incident_store,
            pretrip_workspace_root=workspace_root,
        )
    )
    hardware_router_kwargs: dict[str, Any] = {}
    if hardware_readiness_fixture_path:
        hardware_router_kwargs["fixture_path"] = hardware_readiness_fixture_path
    app.include_router(create_hardware_readiness_router(**hardware_router_kwargs))
    if debug_enabled:
        debug_log = FileRuntimeDebugEventLog(debug_log_path) if debug_log_path else None
        app.include_router(
            create_debug_router(
                debug_log=debug_log,
                agent_trace_log_path=agent_trace_log_path,
                mobile_wearable_ingress_status_path=mobile_wearable_ingress_status_path,
                spatial_imprint_store_path=spatial_imprint_store_path,
                spatial_imprint_trigger_report_path=spatial_imprint_trigger_report_path,
            )
        )
        app.include_router(create_debug_page_router())

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "artifact_kind": "phase4_admin_runtime_health",
            "runtime_profile": env.get(
                "SCOUT_RUNTIME_PROFILE",
                "pi-phase4-admin-preview",
            ),
            "data_root": str(data_root),
            "pretrip_workspace_root": str(workspace_root),
            "incident_store": str(incident_store),
            "routes": {
                "pretrip_admin": "/admin/pretrip",
                "pretrip_project": "/admin/pretrip/projects/chilai_nanhua_day1",
                "wearable_inventory": "/admin/wearables",
                "wearable_validate": "/admin/wearables/validate",
                "wearable_import": "/admin/wearables/import",
                "wearable_energy_refresh": "/admin/wearables/refresh-energy",
                "pretrip_energy_projection_refresh": (
                    "/admin/pretrip/projects/{project_id}/refresh-energy-projection"
                ),
                "pretrip_companion_match_refresh": (
                    "/admin/pretrip/projects/{project_id}/refresh-companion-match"
                ),
                "pretrip_energy_feedback_refresh": (
                    "/admin/pretrip/projects/{project_id}/refresh-energy-feedback"
                ),
                "assistant_status": "/assistant/status" if assistant_enabled else None,
                "hardware_readiness": "/admin/hardware-readiness",
                "hardware_readiness_context": "/admin/hardware-readiness/context",
                "debug_admin": "/admin/debug" if debug_enabled else None,
                "debug_events": "/debug/events" if debug_enabled else None,
                "debug_mobile_wearable_ingress": (
                    "/debug/mobile-wearable/ingress" if debug_enabled else None
                ),
                "agent_trace_log": str(agent_trace_log_path) if agent_trace_log_path else None,
                "spatial_imprint_store": (
                    str(spatial_imprint_store_path) if spatial_imprint_store_path else None
                ),
                "spatial_imprint_trigger_report": (
                    str(spatial_imprint_trigger_report_path)
                    if spatial_imprint_trigger_report_path
                    else None
                ),
            },
            "auth": _admin_auth_status(auth_config),
            "assistant_context_registry": assistant_context_registry_status,
            "ingress_observers": ingress_observer_supervisor.status(),
            "boundaries": _runtime_boundaries(
                env,
                assistant_enabled=assistant_enabled,
                debug_enabled=debug_enabled,
            ),
        }

    @app.get("/phase4/admin-preview/status")
    def phase4_admin_preview_status() -> dict[str, Any]:
        return {
            "artifact_kind": "phase4_admin_hardware_preview_status",
            "status": "ready",
            "lan_visible": True,
            "recommended_mac_url": "http://scout.local:9110/admin/pretrip",
            "service_port_policy": {
                "hardware_runtime_port": 9099,
                "admin_preview_host_port": 9110,
                "shares_runtime_port": False,
            },
            "tile_cache": {
                "osm_cache_root": env.get(
                    "SCOUT_ADMIN_OSM_TILE_CACHE_ROOT",
                    "/data/scout/osm-tiles",
                ),
                "raster_cache_root": env.get(
                    "SCOUT_ADMIN_RASTER_TILE_CACHE_ROOT",
                    "/data/scout/raster-tiles",
                ),
                "repo_fixture_write_allowed": False,
            },
            "auth": _admin_auth_status(auth_config),
            "assistant_context_registry": assistant_context_registry_status,
            "ingress_observers": ingress_observer_supervisor.status(),
            "boundaries": _runtime_boundaries(
                env,
                assistant_enabled=assistant_enabled,
                debug_enabled=debug_enabled,
            ),
        }

    if assistant_enabled:

        @app.get("/assistant/status")
        def assistant_status() -> dict[str, Any]:
            return dict(provider_status)

        @app.post("/assistant/query")
        def assistant_query(query: ScoutAssistantQuery) -> ScoutAssistantResponse:
            return answer_assistant_query_safely(
                provider,
                query,
                sources=_assistant_sources(
                    query,
                    pretrip_workspace_root=workspace_root,
                    live_navigation_evidence_dir=live_navigation_evidence_dir,
                    fallback_resolver=assistant_context_resolver,
                ),
            )

    return app


def _mobile_wearable_ingress_status_path(env: Mapping[str, str]) -> Path:
    explicit_path = (env.get("SCOUT_MOBILE_WEARABLE_INGRESS_STATUS_PATH") or "").strip()
    if explicit_path:
        return Path(explicit_path).expanduser()

    evidence_dir = (env.get("SCOUT_SENSORLOGGER_MQTT_EVIDENCE_DIR") or "").strip()
    if evidence_dir:
        return Path(evidence_dir).expanduser() / "sensorlogger_mqtt_status.json"

    data_root = Path(env.get("SCOUT_DATA_ROOT", str(DEFAULT_DATA_ROOT))).expanduser()
    return data_root / "admin" / "ingress" / "sensorlogger_mqtt" / "sensorlogger_mqtt_status.json"


def _runtime_boundaries(
    env: Mapping[str, str],
    *,
    assistant_enabled: bool,
    debug_enabled: bool,
) -> dict[str, Any]:
    return {
        "phase1_field_runtime_started": False,
        "phase1_safety_decision_mutation_allowed": False,
        "safety_api_mutation_allowed": False,
        "phase2_writeback_allowed": False,
        "repo_fixture_write_allowed": False,
        "local_pretrip_workspace_write_allowed": True,
        "outbound_messages_allowed": False,
        "hardware_control_allowed": False,
        "assistant_enabled": assistant_enabled,
        "assistant_provider": (
            env.get("SCOUT_AI_ASSISTANT_PROVIDER", "mock").strip().lower()
            if assistant_enabled
            else "disabled"
        ),
        "assistant_read_only": assistant_enabled,
        "debug_api_enabled": debug_enabled,
        "debug_projection_clear_allowed": debug_enabled,
        "debug_projection_clear_mutates_runtime": False,
        "weather_live_api_opt_in": _is_true_like(env.get("SCOUT_WEATHER_API_ENABLED")),
        "weather_raw_payloads_embedded": False,
    }


def _assistant_sources(
    query: ScoutAssistantQuery,
    *,
    pretrip_workspace_root: Path | None = None,
    live_navigation_evidence_dir: Path | None = None,
    fallback_resolver=None,
) -> list[AssistantSourceRef]:
    if query.surface == AssistantSurface.PRETRIP:
        project_id = query.project_id or query.context_ref
        if project_id:
            project_root = _assistant_pretrip_project_root(
                pretrip_workspace_root,
                project_id,
            )
            try:
                context = build_pretrip_assistant_context(
                    project_id,
                    project_root=project_root,
                    selected_source_id=query.selected_artifact_id,
                )
                sources = assistant_source_refs_from_context(context, query=query)
                sources = augment_sources_with_configured_live_navigation_evidence(
                    query,
                    sources=sources,
                    evidence_dir=live_navigation_evidence_dir,
                    project_root=project_root,
                )
                return augment_pretrip_sources_with_local_evidence_search(
                    query,
                    sources=sources,
                    project_root=project_root,
                )
            except (FileNotFoundError, KeyError, ModuleNotFoundError, ValueError):
                pass
    if callable(fallback_resolver):
        return fallback_resolver(query)
    return query_source_refs(query)


def _assistant_pretrip_project_root(
    pretrip_workspace_root: Path | None,
    project_id: str,
) -> Path | None:
    if pretrip_workspace_root is None:
        return None
    candidate = Path(pretrip_workspace_root).expanduser() / project_id
    if (candidate / "project.json").exists():
        return candidate
    return None


def _optional_path(value: str | None) -> Path | None:
    if value is None or not value.strip():
        return None
    return Path(value).expanduser()


def _admin_auth_config(env: Mapping[str, str]) -> dict[str, Any]:
    required = _is_true_like(env.get("SCOUT_ADMIN_AUTH_REQUIRED"))
    username = env.get("SCOUT_ADMIN_BASIC_USERNAME", DEFAULT_ADMIN_BASIC_USERNAME)
    token = env.get("SCOUT_ADMIN_ACCESS_TOKEN")
    token_file = env.get("SCOUT_ADMIN_ACCESS_TOKEN_FILE")
    token_source = "env" if token else None
    if not token and token_file:
        path = Path(token_file).expanduser()
        try:
            token = path.read_text(encoding="utf-8").strip()
            token_source = "file"
        except OSError:
            token = None
            token_source = "file_unreadable"
    configured = bool(token)
    return {
        "required": required,
        "username": username,
        "token": token,
        "token_configured": configured,
        "token_source": token_source,
        "misconfigured": required and not configured,
    }


def _admin_auth_status(auth_config: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "required": bool(auth_config["required"]),
        "scheme": "basic_or_bearer_token",
        "basic_username": auth_config["username"],
        "token_configured": bool(auth_config["token_configured"]),
        "token_source": auth_config["token_source"],
        "token_value_exposed": False,
        "misconfigured": bool(auth_config["misconfigured"]),
    }


def _admin_auth_allowed(request: Request, auth_config: Mapping[str, Any]) -> bool:
    if request.url.path == "/health":
        return True
    if not auth_config["required"]:
        return True
    token = auth_config["token"]
    if not token:
        return False

    header = request.headers.get("authorization", "")
    return _bearer_token_valid(header, token) or _basic_token_valid(
        header,
        username=str(auth_config["username"]),
        token=token,
    )


def _bearer_token_valid(header: str, token: str) -> bool:
    prefix = "Bearer "
    if not header.startswith(prefix):
        return False
    supplied = header.removeprefix(prefix).strip()
    return bool(supplied) and compare_digest(supplied, token)


def _basic_token_valid(header: str, *, username: str, token: str) -> bool:
    prefix = "Basic "
    if not header.startswith(prefix):
        return False
    try:
        decoded = b64decode(header.removeprefix(prefix), validate=True).decode("utf-8")
    except Exception:
        return False
    supplied_username, separator, supplied_token = decoded.partition(":")
    if separator != ":":
        return False
    return compare_digest(supplied_username, username) and compare_digest(
        supplied_token,
        token,
    )


def _is_true_like(value: str | None) -> bool:
    return value is not None and value.strip().lower() in {"1", "true", "yes", "y", "on"}


app = create_phase4_admin_runtime_app()
