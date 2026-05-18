from __future__ import annotations

import argparse
import json
import shlex
from pathlib import Path
from typing import Any

from runtime_debug_ui_demo import runtime_debug_ui_demo_summary, write_runtime_debug_ui_demo


REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_DEBUG_LOG_PATH = Path("/tmp/scout-phase35-ui-demo.jsonl")
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9099


def prepare_phase35_debug_demo(
    *,
    debug_log_path: Path | str = DEFAULT_DEBUG_LOG_PATH,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    replace: bool = True,
) -> dict[str, Any]:
    resolved_debug_log_path = Path(debug_log_path)
    demo = write_runtime_debug_ui_demo(
        resolved_debug_log_path,
        replace=replace,
    )
    return {
        "debug_log_path": str(resolved_debug_log_path),
        "url": f"http://{host}:{port}/admin/debug",
        "server_command": build_phase35_debug_server_command(
            debug_log_path=resolved_debug_log_path,
            host=host,
            port=port,
        ),
        "verification_endpoints": [
            f"http://{host}:{port}/debug/events",
            f"http://{host}:{port}/debug/state",
            f"http://{host}:{port}/debug/messages",
        ],
        "debug_boundary": {
            "read_only": True,
            "phase1_mutation_allowed": False,
            "phase2_writeback_allowed": False,
            "real_outbound_transport_allowed": False,
            "hardware_required": False,
        },
        "demo": runtime_debug_ui_demo_summary(demo),
    }


def build_phase35_debug_server_command(
    *,
    debug_log_path: Path | str,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
) -> str:
    debug_log = shlex.quote(str(debug_log_path))
    return (
        "SCOUT_DEBUG_API_ENABLED=1 "
        f"SCOUT_DEBUG_LOG_PATH={debug_log} "
        "SCOUT_SAFETY_ENABLED=false "
        f"{shlex.quote(str(REPO_ROOT / 'venv' / 'bin' / 'python'))} "
        "-m uvicorn server:app "
        f"--host {shlex.quote(host)} --port {int(port)}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare a repeatable Scout Phase 3.5 debug UI demo log."
    )
    parser.add_argument(
        "--debug-log",
        type=Path,
        default=DEFAULT_DEBUG_LOG_PATH,
        help="JSONL path to write. Defaults to /tmp/scout-phase35-ui-demo.jsonl.",
    )
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--no-replace",
        dest="replace",
        action="store_false",
        default=True,
        help="Fail if the target debug log already exists.",
    )
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = prepare_phase35_debug_demo(
        debug_log_path=args.debug_log,
        host=args.host,
        port=args.port,
        replace=args.replace,
    )
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
