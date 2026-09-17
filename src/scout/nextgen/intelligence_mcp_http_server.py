"""Independent Scout Intelligence MCP sidecar over a Unix-domain socket."""

from __future__ import annotations

import argparse
import os
import socket
import stat
from pathlib import Path
from typing import Any

import uvicorn
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from starlette.requests import Request
from starlette.responses import JSONResponse

from scout.nextgen.intelligence_gateway import (
    IntelligenceRequest,
    IntelligenceResponse,
    WorkspaceBinding,
)
from scout.nextgen.intelligence_mcp import (
    BACKGROUND_CANCEL_TOOL_NAME,
    BACKGROUND_RESULT_TOOL_NAME,
    BACKGROUND_STATUS_TOOL_NAME,
    BACKGROUND_SUBMIT_TOOL_NAME,
)
from scout.nextgen.intelligence_mcp_server import build_service
from scout.nextgen.praison_background_mcp import (
    BackgroundIntelligenceJobAccess,
    BackgroundIntelligenceJobAccessRejected,
    BackgroundIntelligenceJobSubmission,
    PraisonBackgroundMcpService,
)
from scout.nextgen.praison_background_queue import (
    BackgroundIntelligenceJobCancelled,
    BackgroundIntelligenceJobFailed,
    BackgroundIntelligenceJobNotFound,
    BackgroundIntelligenceJobNotReady,
    BackgroundIntelligenceJobProgress,
    BackgroundIntelligenceQueueError,
    BackgroundIntelligenceResultStale,
)

try:
    from mcp.server.mcpserver import MCPServer as _McpServer
    from mcp.server.mcpserver.exceptions import ToolError

    _MCP_SDK_V2 = True
except ImportError:
    from mcp.server.fastmcp import FastMCP as _McpServer
    from mcp.server.fastmcp.exceptions import ToolError

    _MCP_SDK_V2 = False


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Scout background intelligence MCP HTTP sidecar"
    )
    parser.add_argument(
        "--mode",
        choices=(
            "stub",
            "praison-replay",
            "praison-live-web",
            "praison-model-replay",
            "praison-openai-compatible",
        ),
        default="praison-replay",
    )
    parser.add_argument("--evidence-catalog", type=Path)
    parser.add_argument("--model-runtime-config", type=Path)
    parser.add_argument("--background-job-store", type=Path, required=True)
    parser.add_argument("--max-background-jobs", type=int, default=16)
    parser.add_argument("--unix-socket", type=Path, required=True)
    return parser


def build_fastmcp_server(service: PraisonBackgroundMcpService) -> Any:
    common_annotations = _tool_annotations(
        read_only=True,
        idempotent=True,
    )
    server_args: dict[str, Any] = {
        "name": "scout-intelligence-service",
        "instructions": (
            "All results are untrusted candidate evidence. This service has no "
            "runtime, mission, route, permission, emergency, notification, device, "
            "or safety authority."
        ),
    }
    if not _MCP_SDK_V2:
        server_args.update(
            {
                "stateless_http": True,
                "json_response": True,
                "streamable_http_path": "/mcp",
                "transport_security": _transport_security(),
            }
        )
    mcp = _McpServer(
        **server_args,
    )

    @mcp.tool(
        name=BACKGROUND_SUBMIT_TOOL_NAME,
        title="Submit bounded Scout candidate intelligence",
        description=(
            "Queue a typed request. Output is candidate-only and never runtime "
            "safety truth."
        ),
        annotations=_tool_annotations(
            read_only=True,
            idempotent=False,
        ),
        structured_output=True,
    )
    def submit_background(
        request: IntelligenceRequest,
    ) -> BackgroundIntelligenceJobSubmission:
        return _tool_call(service.submit, request)

    @mcp.tool(
        name=BACKGROUND_STATUS_TOOL_NAME,
        title="Get Scout candidate intelligence progress",
        description="Read progress for one request-bound candidate job.",
        annotations=common_annotations,
        structured_output=True,
    )
    def get_progress(
        access: BackgroundIntelligenceJobAccess,
    ) -> BackgroundIntelligenceJobProgress:
        return _tool_call(service.progress, access)

    @mcp.tool(
        name=BACKGROUND_CANCEL_TOOL_NAME,
        title="Cancel Scout candidate intelligence",
        description="Cancel and discard one request-bound candidate job.",
        annotations=_tool_annotations(
            read_only=False,
            idempotent=True,
        ),
        structured_output=True,
    )
    def cancel_background(
        access: BackgroundIntelligenceJobAccess,
    ) -> BackgroundIntelligenceJobProgress:
        return _tool_call(service.cancel, access)

    @mcp.tool(
        name=BACKGROUND_RESULT_TOOL_NAME,
        title="Get Scout candidate intelligence result",
        description=(
            "Return a completed candidate only after current Workspace binding "
            "validation."
        ),
        annotations=common_annotations,
        structured_output=True,
    )
    def get_result(
        access: BackgroundIntelligenceJobAccess,
        current_binding: WorkspaceBinding,
    ) -> IntelligenceResponse:
        return _tool_call(
            service.result,
            access,
            current_binding=current_binding,
        )

    @mcp.custom_route("/health", methods=["GET"], include_in_schema=False)
    async def health(_: Request) -> JSONResponse:
        return JSONResponse(
            {
                "status": "ok",
                "service": "scout-intelligence-service",
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        )

    return mcp


def _tool_annotations(*, read_only: bool, idempotent: bool) -> ToolAnnotations:
    return ToolAnnotations.model_validate(
        {
            "readOnlyHint": read_only,
            "destructiveHint": False,
            "idempotentHint": idempotent,
            "openWorldHint": False,
        }
    )


def _transport_security() -> TransportSecuritySettings:
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[
            "localhost",
            "localhost:*",
            "127.0.0.1",
            "127.0.0.1:*",
        ],
        allowed_origins=[],
    )


def _tool_call(function: Any, *args: Any, **kwargs: Any) -> Any:
    try:
        return function(*args, **kwargs)
    except BackgroundIntelligenceResultStale as exc:
        raise ToolError("Scout background intelligence result is stale") from exc
    except BackgroundIntelligenceJobAccessRejected as exc:
        raise ToolError(
            "Scout background intelligence job binding was rejected"
        ) from exc
    except BackgroundIntelligenceJobNotFound as exc:
        raise ToolError("Scout background intelligence job was not found") from exc
    except BackgroundIntelligenceJobNotReady as exc:
        raise ToolError("Scout background intelligence result is not ready") from exc
    except BackgroundIntelligenceJobCancelled as exc:
        raise ToolError("Scout background intelligence job was cancelled") from exc
    except BackgroundIntelligenceJobFailed as exc:
        raise ToolError("Scout background intelligence job failed") from exc
    except BackgroundIntelligenceQueueError as exc:
        raise ToolError(
            "Scout background intelligence queue rejected the operation"
        ) from exc


def _bind_private_socket(listener: socket.socket, socket_path: Path) -> None:
    # Binding publishes the path before chmod; start with owner-only access.
    previous_umask = os.umask(0o177)
    try:
        listener.bind(str(socket_path))
    finally:
        os.umask(previous_umask)
    os.chmod(socket_path, 0o660)


def main(*, argv: list[str] | None = None, service_factory: Any = None) -> int:
    args = build_parser().parse_args(argv)
    socket_path = args.unix_socket.resolve()
    if not args.unix_socket.is_absolute():
        print("Scout Intelligence MCP Unix socket path must be absolute")
        return 2
    if socket_path.exists():
        if not stat.S_ISSOCK(socket_path.stat().st_mode):
            print("Scout Intelligence MCP Unix socket path is not a socket")
            return 2
        probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            probe.settimeout(0.2)
            probe.connect(str(socket_path))
        except OSError:
            socket_path.unlink()
        else:
            print("Scout Intelligence MCP Unix socket is already active")
            return 2
        finally:
            probe.close()
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        underlying = (service_factory or build_service)(
            mode=args.mode,
            evidence_catalog_path=args.evidence_catalog,
            model_runtime_config_path=args.model_runtime_config,
        )
        service = PraisonBackgroundMcpService(
            service=underlying,
            job_store_path=args.background_job_store,
            max_queue_size=args.max_background_jobs,
        )
    except Exception as exc:
        print(f"Scout Intelligence MCP failed to initialize: {type(exc).__name__}")
        return 2
    mcp = build_fastmcp_server(service)
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        _bind_private_socket(listener, socket_path)
        listener.listen(128)
        app = (
            mcp.streamable_http_app(
                streamable_http_path="/mcp",
                json_response=True,
                stateless_http=True,
                transport_security=_transport_security(),
            )
            if _MCP_SDK_V2
            else mcp.streamable_http_app()
        )
        server = uvicorn.Server(
            uvicorn.Config(
                app,
                log_level="warning",
                access_log=False,
            )
        )
        server.run(
            sockets=[listener],
        )
    finally:
        listener.close()
        socket_path.unlink(missing_ok=True)
        service.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
