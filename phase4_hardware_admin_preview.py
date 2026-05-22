from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_HARDWARE_HOST = "scout.local"
DEFAULT_HOST_PORT = 9110
CONTAINER_PORT = 9099
COMPOSE_FILE = "docker-compose.pi.admin.yml"


def prepare_phase4_hardware_admin_preview(
    *,
    hardware_host: str = DEFAULT_HARDWARE_HOST,
    host_port: int = DEFAULT_HOST_PORT,
    enable_live_weather: bool = False,
) -> dict[str, Any]:
    base_url = f"http://{hardware_host}:{int(host_port)}"
    env = {
        "SCOUT_RUNTIME_PROFILE": "pi-phase4-admin-preview",
        "SCOUT_SAFETY_ENABLED": "false",
        "SCOUT_AI_ASSISTANT_ENABLED": "1",
        "SCOUT_AI_ASSISTANT_PROVIDER": "mock",
        "SCOUT_WEATHER_API_ENABLED": "true" if enable_live_weather else "false",
        "SCOUT_WEATHER_API_PROVIDER": "open_meteo",
        "SCOUT_PRETRIP_WORKSPACE_ROOT": "/data/scout/admin/pretrip-workspaces",
        "SCOUT_ADMIN_OSM_TILE_CACHE_ROOT": "/data/scout/osm-tiles",
        "SCOUT_ADMIN_RASTER_TILE_CACHE_ROOT": "/data/scout/raster-tiles",
        "SCOUT_ADMIN_AUTH_REQUIRED": "true",
        "SCOUT_ADMIN_BASIC_USERNAME": "scout-admin",
        "SCOUT_ADMIN_ACCESS_TOKEN_FILE": "/data/scout/admin/secrets/phase4-admin-token",
        "SCOUT_DEBUG_API_ENABLED": "true",
        "SCOUT_DEBUG_LOG_PATH": "/data/scout/admin/debug/runtime-debug-events.jsonl",
    }
    return {
        "artifact_kind": "phase4_hardware_admin_preview_plan",
        "status": "ready_to_deploy",
        "compose_file": COMPOSE_FILE,
        "service": "scout-phase4-admin",
        "image": "scout-fusion/pi-phase4-admin:preview",
        "runtime_port_policy": {
            "existing_runtime_host_port": 9099,
            "admin_preview_host_port": int(host_port),
            "container_port": CONTAINER_PORT,
            "shares_existing_runtime_port": False,
        },
        "urls": {
            "health": f"{base_url}/health",
            "pretrip_admin": f"{base_url}/admin/pretrip",
            "pretrip_admin_local_tiles": f"{base_url}/admin/pretrip?tileSource=local",
            "pretrip_project": f"{base_url}/admin/pretrip/projects/chilai_nanhua_day1",
            "weather_overlay": (
                f"{base_url}/admin/pretrip/projects/chilai_nanhua_day1/weather-overlay"
            ),
            "assistant_status": f"{base_url}/assistant/status",
            "debug_admin": f"{base_url}/admin/debug",
            "debug_events": f"{base_url}/debug/events",
            "preview_status": f"{base_url}/phase4/admin-preview/status",
        },
        "operator_commands": {
            "create_token": (
                "mkdir -p /data/scout/admin/secrets && "
                "openssl rand -base64 32 > /data/scout/admin/secrets/phase4-admin-token "
                "&& chmod 600 /data/scout/admin/secrets/phase4-admin-token"
            ),
            "build": f"docker compose -f {COMPOSE_FILE} build scout-phase4-admin",
            "start": f"docker compose -f {COMPOSE_FILE} up -d scout-phase4-admin",
            "logs": f"docker compose -f {COMPOSE_FILE} logs -f scout-phase4-admin",
            "stop": f"docker compose -f {COMPOSE_FILE} down",
        },
        "environment": env,
        "tile_cache": {
            "osm_cache_root": "/data/scout/osm-tiles",
            "raster_cache_root": "/data/scout/raster-tiles",
            "capacity_limit_bytes": 10 * 1024 * 1024 * 1024,
            "repo_fixture_write_allowed": False,
        },
        "network_expectations": {
            "mac_browser_uses_lan_hostname": True,
            "public_osm_loaded_by_browser": True,
            "local_osm_proxy_external_fetch_allowed": False,
            "open_meteo_live_weather_enabled": enable_live_weather,
            "external_webhook_send_enabled": False,
        },
        "boundaries": {
            "does_not_replace_pi_runtime_service": True,
            "admin_auth_required": True,
            "admin_token_value_embedded": False,
            "phase1_field_runtime_started": False,
            "phase1_runtime_mutation_allowed": False,
            "phase2_writeback_allowed": False,
            "assistant_provider": "mock",
            "assistant_read_only": True,
            "debug_api_enabled": True,
            "debug_projection_log_path": "/data/scout/admin/debug/runtime-debug-events.jsonl",
            "debug_projection_clear_mutates_runtime": False,
            "repo_fixture_write_allowed": False,
            "local_pretrip_workspace_write_allowed": True,
            "outbound_messages_allowed": False,
            "hardware_control_allowed": False,
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Print the Scout hardware Phase 4 admin LAN preview deploy plan."
    )
    parser.add_argument("--hardware-host", default=DEFAULT_HARDWARE_HOST)
    parser.add_argument("--host-port", type=int, default=DEFAULT_HOST_PORT)
    parser.add_argument("--enable-live-weather", action="store_true")
    parser.add_argument("--pretty", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    plan = prepare_phase4_hardware_admin_preview(
        hardware_host=args.hardware_host,
        host_port=args.host_port,
        enable_live_weather=args.enable_live_weather,
    )
    print(json.dumps(plan, ensure_ascii=False, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
