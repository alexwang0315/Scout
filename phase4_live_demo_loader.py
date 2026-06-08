from __future__ import annotations

import argparse
import json
import shlex
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9099


def prepare_phase4_live_demo(
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    enable_live_weather: bool = True,
    enable_assistant: bool = True,
) -> dict[str, Any]:
    base_url = f"http://{host}:{int(port)}"
    env = build_phase4_live_demo_env(
        enable_live_weather=enable_live_weather,
        enable_assistant=enable_assistant,
    )
    return {
        "artifact_kind": "phase4_live_demo_plan",
        "status": "ready_to_start",
        "server_command": build_phase4_live_demo_server_command(
            host=host,
            port=port,
            env=env,
        ),
        "urls": {
            "pretrip_admin": f"{base_url}/admin/pretrip",
            "pretrip_admin_local_tiles": f"{base_url}/admin/pretrip?tileSource=local",
            "after_action_admin": f"{base_url}/admin",
            "after_action_admin_local_tiles": f"{base_url}/admin?tileSource=local",
            "assistant_status": f"{base_url}/assistant/status",
            "weather_overlay": (
                f"{base_url}/admin/pretrip/projects/chilai_nanhua_day1/weather-overlay"
            ),
        },
        "verification_endpoints": [
            f"{base_url}/admin/pretrip",
            f"{base_url}/admin/pretrip/projects/chilai_nanhua_day1",
            f"{base_url}/admin/pretrip/projects/chilai_nanhua_day1/weather-overlay",
            f"{base_url}/assistant/status",
            f"{base_url}/admin",
        ],
        "environment": env,
        "network_expectations": {
            "public_osm_loaded_by_browser": True,
            "open_meteo_live_weather_enabled": enable_live_weather,
            "local_osm_proxy_external_fetch_allowed": False,
            "local_raster_proxy_external_fetch_allowed": False,
            "external_webhook_send_enabled": False,
        },
        "boundaries": {
            "phase1_runtime_mutation_allowed": False,
            "phase2_writeback_allowed": False,
            "assistant_provider": "mock" if enable_assistant else "disabled",
            "assistant_read_only": enable_assistant,
            "weather_raw_payloads_embedded": False,
            "repo_fixture_write_allowed": False,
        },
        "notes": [
            "Use public tile mode for the clearest online basemap demo.",
            "Use tileSource=local to demonstrate the local OSM proxy and offline fallback.",
            "Open-Meteo live weather is opt-in and summary-only.",
        ],
    }


def build_phase4_live_demo_env(
    *,
    enable_live_weather: bool,
    enable_assistant: bool,
) -> dict[str, str]:
    env = {
        "SCOUT_SAFETY_ENABLED": "false",
    }
    if enable_assistant:
        env.update(
            {
                "SCOUT_AI_ASSISTANT_ENABLED": "1",
                "SCOUT_AI_ASSISTANT_PROVIDER": "mock",
            }
        )
    if enable_live_weather:
        env.update(
            {
                "SCOUT_WEATHER_API_ENABLED": "true",
                "SCOUT_WEATHER_API_PROVIDER": "open_meteo",
            }
        )
    return env


def build_phase4_live_demo_server_command(
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    env: dict[str, str] | None = None,
) -> str:
    resolved_env = env or build_phase4_live_demo_env(
        enable_live_weather=True,
        enable_assistant=True,
    )
    env_prefix = " ".join(
        f"{key}={shlex.quote(value)}" for key, value in sorted(resolved_env.items())
    )
    python_bin = shlex.quote(str(REPO_ROOT / "venv" / "bin" / "python"))
    return (
        f"{env_prefix} {python_bin} -m uvicorn server:app "
        f"--host {shlex.quote(host)} --port {int(port)}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Print the Phase 4 live admin demo launch plan."
    )
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-live-weather", action="store_true")
    parser.add_argument("--no-assistant", action="store_true")
    parser.add_argument("--pretty", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    plan = prepare_phase4_live_demo(
        host=args.host,
        port=args.port,
        enable_live_weather=not args.no_live_weather,
        enable_assistant=not args.no_assistant,
    )
    print(json.dumps(plan, ensure_ascii=False, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
