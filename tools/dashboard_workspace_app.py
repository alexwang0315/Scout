from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from starlette.middleware.gzip import GZipMiddleware

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from admin_api import create_admin_router  # noqa: E402
from assistant_api import (  # noqa: E402
    create_assistant_provider_from_env,
    create_assistant_provider_status,
    create_assistant_router,
)
from assistant_context import create_assistant_context_resolver  # noqa: E402
from debug_api import create_debug_page_router, create_debug_router  # noqa: E402
from debug_event_provenance import DebugEventIngestionChannel  # noqa: E402
from hardware_readiness_api import create_hardware_readiness_router  # noqa: E402
from mock_outbound_transport import MockOutboundTransport  # noqa: E402
from runtime_debug_log import MemoryRuntimeDebugEventLog  # noqa: E402
from scout_env import load_scout_env_files  # noqa: E402
from tools.admin_ui_smoke_app import _debug_events  # noqa: E402


def load_repo_env(root: Path = ROOT) -> None:
    load_scout_env_files(repo_root=root)


def create_dashboard_workspace_app(*, workspace_root: Path) -> FastAPI:
    load_repo_env()
    os.environ.setdefault("SCOUT_AI_ASSISTANT_PROVIDER", "pydantic_ai")
    os.environ.setdefault(
        "SCOUT_AI_ASSISTANT_CONFIG_PATH",
        str(ROOT / "configs" / "assistant-models.dashboard-aihat2.json"),
    )
    os.environ.setdefault("SCOUT_PRETRIP_WORKSPACE_ROOT", str(workspace_root))
    os.environ.setdefault("SCOUT_AI_ASSISTANT_TIMEOUT_SECONDS", "45")
    os.environ.setdefault("SCOUT_AI_ASSISTANT_MAX_CONTEXT_CHARS", "24000")

    app = FastAPI(title="Scout Dashboard Workspace App")
    app.add_middleware(GZipMiddleware, minimum_size=1_024, compresslevel=5)
    app.include_router(create_admin_router(pretrip_workspace_root=workspace_root))

    debug_log = MemoryRuntimeDebugEventLog(_debug_events())
    transport = MockOutboundTransport(
        session_id="debug_session.dashboard_workspace",
        mission_id="mission.dashboard_workspace",
        debug_log=debug_log,
        timestamp_factory=lambda: "2026-07-09T00:00:00Z",
    )
    app.include_router(
        create_debug_router(
            debug_log=debug_log,
            debug_log_ingestion_channel=DebugEventIngestionChannel.SMOKE_HARNESS,
            message_source=transport,
        )
    )
    app.include_router(create_debug_page_router())
    app.include_router(create_hardware_readiness_router())

    assistant_provider = create_assistant_provider_from_env(os.environ)
    app.include_router(
        create_assistant_router(
            provider=assistant_provider,
            context_resolver=create_assistant_context_resolver(
                debug_event_log=debug_log,
                pretrip_workspace_root=workspace_root,
            ),
            provider_status=create_assistant_provider_status(
                provider=assistant_provider,
                environ=os.environ,
            ),
        )
    )
    return app


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Serve Scout dashboard with real local workspaces and assistant provider."
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=9099, type=int)
    parser.add_argument(
        "--workspace-root",
        default="/Users/alexwang0315/workspace",
        type=Path,
    )
    args = parser.parse_args()
    app = create_dashboard_workspace_app(workspace_root=args.workspace_root)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
