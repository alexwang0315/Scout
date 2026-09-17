"""Run or preflight the Scout AI OS development server from a source checkout."""

from __future__ import annotations

import argparse
import json
import os
import platform
import socket
from collections.abc import Sequence
from typing import Any


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9120
DATABASE_PATH_ENV = "SCOUT_AI_OS_DATABASE_PATH"
DEFAULT_DEV_DATABASE_PATH = ":memory:"


def build_dev_server_preflight(
    *,
    host: str,
    port: int,
    database_path: str = DEFAULT_DEV_DATABASE_PATH,
) -> dict[str, Any]:
    """Import the real app and return a secret-free readiness receipt."""

    os.environ[DATABASE_PATH_ENV] = database_path
    from scout.main import app

    route_paths = sorted(str(path) for path in app.openapi().get("paths", {}))
    required_routes = {"/capabilities", "/requests"}
    missing_routes = sorted(required_routes.difference(route_paths))
    return {
        "artifact_kind": "scout_ai_os_dev_server_preflight",
        "schema_version": "scout.ai_os.dev_server_preflight.v1",
        "status": "ready" if not missing_routes else "blocked",
        "hostname": socket.gethostname(),
        "machine": platform.machine(),
        "host": host,
        "port": port,
        "lan_exposed": host in {"0.0.0.0", "::"},
        "database": {
            "mode": "memory" if database_path == ":memory:" else "file",
            "path_ref": database_path,
        },
        "required_routes": sorted(required_routes),
        "missing_routes": missing_routes,
        "route_count": len(route_paths),
        "boundary": {
            "starts_server": False,
            "loads_secret_values": False,
            "calls_external_model": False,
            "writes_database_file": database_path != ":memory:",
            "mutates_phase1_safety_truth": False,
            "sends_outbound": False,
            "controls_hardware": False,
        },
    }


def _port(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("port must be an integer") from exc
    if not 1 <= parsed <= 65_535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return parsed


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run Scout AI OS from the current source checkout.",
    )
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=_port, default=DEFAULT_PORT)
    parser.add_argument(
        "--database-path",
        default=os.getenv(DATABASE_PATH_ENV, DEFAULT_DEV_DATABASE_PATH),
        help=(
            "SQLite path for development state; defaults to isolated in-memory "
            "state and honors SCOUT_AI_OS_DATABASE_PATH."
        ),
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Import the real app and print a readiness receipt without serving.",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable uvicorn source reload for an interactive development session.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.check:
        report = build_dev_server_preflight(
            host=args.host,
            port=args.port,
            database_path=args.database_path,
        )
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if report["status"] == "ready" else 1

    os.environ[DATABASE_PATH_ENV] = args.database_path

    import uvicorn

    uvicorn.run(
        "scout.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint.
    raise SystemExit(main())
