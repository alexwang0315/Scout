from __future__ import annotations

import os
from base64 import b64decode
from hmac import compare_digest
from pathlib import Path
from typing import Any, Mapping

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from admin_api import create_admin_router
from assistant_models import AssistantSourceRef, ScoutAssistantQuery, ScoutAssistantResponse
from assistant_provider import MockAssistantProvider
from debug_api import create_debug_page_router, create_debug_router
from hardware_readiness_api import create_hardware_readiness_router
from runtime_debug_log import FileRuntimeDebugEventLog


DEFAULT_DATA_ROOT = Path("/data/scout")
DEFAULT_ADMIN_WORKSPACE_ROOT = DEFAULT_DATA_ROOT / "admin" / "pretrip-workspaces"
DEFAULT_INCIDENT_STORE = DEFAULT_DATA_ROOT / "incidents"
DEFAULT_ADMIN_BASIC_USERNAME = "scout-admin"


def create_phase4_admin_runtime_app(
    *,
    environ: Mapping[str, str] | None = None,
) -> FastAPI:
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
    spatial_imprint_store_path = env.get("SCOUT_SPATIAL_IMPRINT_STORE_PATH")
    spatial_imprint_trigger_report_path = env.get("SCOUT_SPATIAL_IMPRINT_TRIGGER_REPORT_PATH")
    hardware_readiness_fixture_path = env.get("SCOUT_HARDWARE_READINESS_FIXTURE_PATH")
    auth_config = _admin_auth_config(env)
    provider = MockAssistantProvider()

    app = FastAPI(
        title="Scout Phase 4 Admin LAN Preview",
        description=(
            "LAN-visible Phase 4 admin preview for Scout hardware. This app exposes "
            "planning/admin surfaces only and does not run the Phase 1 field runtime."
        ),
        version="0.1.0",
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
                "wearable_import": "/admin/wearables/import",
                "wearable_energy_refresh": "/admin/wearables/refresh-energy",
                "pretrip_energy_projection_refresh": (
                    "/admin/pretrip/projects/{project_id}/refresh-energy-projection"
                ),
                "pretrip_companion_match_refresh": (
                    "/admin/pretrip/projects/{project_id}/refresh-companion-match"
                ),
                "assistant_status": "/assistant/status" if assistant_enabled else None,
                "hardware_readiness": "/admin/hardware-readiness",
                "hardware_readiness_context": "/admin/hardware-readiness/context",
                "debug_admin": "/admin/debug" if debug_enabled else None,
                "debug_events": "/debug/events" if debug_enabled else None,
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
            "boundaries": _runtime_boundaries(
                env,
                assistant_enabled=assistant_enabled,
                debug_enabled=debug_enabled,
            ),
        }

    if assistant_enabled:

        @app.get("/assistant/status")
        def assistant_status() -> dict[str, Any]:
            return {
                "read_only": True,
                "model_interpretation": True,
                "provider": "mock",
                "provider_class": type(provider).__name__,
                "runtime_profile": env.get(
                    "SCOUT_RUNTIME_PROFILE",
                    "pi-phase4-admin-preview",
                ),
                "startup_connection_status": "not_checked",
                "config_path_configured": False,
                "config_loaded": False,
                "cloud_only": False,
                "local_fallback_enabled": False,
                "local_fallback_mode": "disabled",
                "manual_verification_required": False,
                "local_fallback_max_concurrency": 1,
                "readiness_starts_local_model": False,
                "local_model_listener_required_for_readiness": False,
                "status_model_switch_allowed": False,
                "token_values_exposed": False,
            }

        @app.post("/assistant/query")
        def assistant_query(query: ScoutAssistantQuery) -> ScoutAssistantResponse:
            return provider.answer(query, sources=_assistant_sources(query))

    return app


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
        "assistant_provider": "mock" if assistant_enabled else "disabled",
        "assistant_read_only": assistant_enabled,
        "debug_api_enabled": debug_enabled,
        "debug_projection_clear_allowed": debug_enabled,
        "debug_projection_clear_mutates_runtime": False,
        "weather_live_api_opt_in": _is_true_like(env.get("SCOUT_WEATHER_API_ENABLED")),
        "weather_raw_payloads_embedded": False,
    }


def _assistant_sources(query: ScoutAssistantQuery) -> list[AssistantSourceRef]:
    refs: list[AssistantSourceRef] = []
    if query.project_id:
        refs.append(
            AssistantSourceRef(
                source_id=query.project_id,
                source_path=(
                    "tests/fixtures/pretrip/projects/"
                    f"{query.project_id}/project.json"
                ),
                evidence_type="pretrip_project",
                selected=True,
            )
        )
    if query.context_ref and query.context_ref != query.project_id:
        refs.append(
            AssistantSourceRef(
                source_id=query.context_ref,
                evidence_type="assistant_context_ref",
                selected=True,
            )
        )
    if query.selected_artifact_id:
        refs.append(
            AssistantSourceRef(
                source_id=query.selected_artifact_id,
                evidence_type="admin_artifact",
                selected=True,
            )
        )
    return refs


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
