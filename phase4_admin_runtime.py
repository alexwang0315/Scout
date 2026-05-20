from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

from fastapi import FastAPI

from admin_api import create_admin_router
from assistant_models import AssistantSourceRef, ScoutAssistantQuery, ScoutAssistantResponse
from assistant_provider import MockAssistantProvider


DEFAULT_DATA_ROOT = Path("/data/scout")
DEFAULT_ADMIN_WORKSPACE_ROOT = DEFAULT_DATA_ROOT / "admin" / "pretrip-workspaces"
DEFAULT_INCIDENT_STORE = DEFAULT_DATA_ROOT / "incidents"


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
    provider = MockAssistantProvider()

    app = FastAPI(
        title="Scout Phase 4 Admin LAN Preview",
        description=(
            "LAN-visible Phase 4 admin preview for Scout hardware. This app exposes "
            "planning/admin surfaces only and does not run the Phase 1 field runtime."
        ),
        version="0.1.0",
    )
    app.include_router(
        create_admin_router(
            incident_store_path=incident_store,
            pretrip_workspace_root=workspace_root,
        )
    )

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
                "assistant_status": "/assistant/status" if assistant_enabled else None,
            },
            "boundaries": _runtime_boundaries(env, assistant_enabled=assistant_enabled),
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
            "boundaries": _runtime_boundaries(env, assistant_enabled=assistant_enabled),
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


def _is_true_like(value: str | None) -> bool:
    return value is not None and value.strip().lower() in {"1", "true", "yes", "y", "on"}


app = create_phase4_admin_runtime_app()
