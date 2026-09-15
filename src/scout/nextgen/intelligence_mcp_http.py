"""Official MCP Streamable HTTP client over a local Unix-domain socket."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

try:
    import mcp.server.mcpserver  # noqa: F401
    import httpx2 as _httpx

    _MCP_SDK_V2 = True
except ImportError:
    import httpx as _httpx

    _MCP_SDK_V2 = False

from scout.nextgen.intelligence_gateway import (
    IntelligenceRequest,
    IntelligenceResponse,
    PydanticContractGateway,
    WorkspaceBinding,
)
from scout.nextgen.intelligence_mcp import (
    BACKGROUND_CANCEL_TOOL_NAME,
    BACKGROUND_RESULT_TOOL_NAME,
    BACKGROUND_STATUS_TOOL_NAME,
    BACKGROUND_SUBMIT_TOOL_NAME,
    IntelligenceMcpProtocolError,
    IntelligenceMcpTimeout,
    IntelligenceMcpUnavailable,
)
from scout.nextgen.praison_background_mcp import (
    BackgroundIntelligenceJobAccess,
    BackgroundIntelligenceJobSubmission,
)
from scout.nextgen.praison_background_queue import (
    BackgroundIntelligenceJobProgress,
)


def probe_intelligence_mcp_http_health(
    unix_socket: Path, *, timeout_seconds: float = 1.0,
) -> tuple[int, bytes]:
    """Read local health with the same owned async transport as MCP calls.

    Keep the HTTP status and body intact: each caller retains its own health
    predicate. Refused or absent sockets must release their transport as well.
    """
    path = Path(unix_socket)
    if not path.is_absolute():
        raise ValueError("Intelligence MCP Unix socket path must be absolute")

    async def read_health() -> tuple[int, bytes]:
        transport = _httpx.AsyncHTTPTransport(uds=str(path), retries=0)
        async with _httpx.AsyncClient(
            transport=transport, timeout=timeout_seconds, trust_env=False,
        ) as client:
            response = await client.get("http://localhost/health")
            return response.status_code, response.content

    try:
        return asyncio.run(read_health())
    except _httpx.TransportError as exc:
        raise IntelligenceMcpUnavailable("Intelligence MCP health transport unavailable") from exc


@dataclass(frozen=True)
class IntelligenceMcpHttpClientConfig:
    unix_socket: Path
    endpoint_url: str = "http://localhost/mcp"
    timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        socket_path = Path(self.unix_socket)
        if not socket_path.is_absolute():
            raise ValueError("Intelligence MCP Unix socket path must be absolute")
        parsed = urlsplit(self.endpoint_url)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"localhost", "127.0.0.1"}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "Intelligence MCP Unix-socket endpoint must use local credential-free HTTP"
            )
        if not 0.25 <= float(self.timeout_seconds) <= 300:
            raise ValueError("Intelligence MCP timeout must be between 0.25 and 300 seconds")


class IntelligenceMcpHttpClient:
    """Synchronous Scout facade for stateless local MCP HTTP calls."""

    def __init__(self, config: IntelligenceMcpHttpClientConfig) -> None:
        self.config = config

    def submit_background(
        self,
        request: IntelligenceRequest,
    ) -> BackgroundIntelligenceJobSubmission:
        payload = self._call_tool(
            BACKGROUND_SUBMIT_TOOL_NAME,
            {"request": request.model_dump(mode="json")},
        )
        submission = BackgroundIntelligenceJobSubmission.model_validate(payload)
        _validate_access_request(submission.access, request)
        return submission

    def background_progress(
        self,
        access: BackgroundIntelligenceJobAccess,
    ) -> BackgroundIntelligenceJobProgress:
        payload = self._call_tool(
            BACKGROUND_STATUS_TOOL_NAME,
            {"access": access.model_dump(mode="json")},
        )
        progress = BackgroundIntelligenceJobProgress.model_validate(payload)
        _validate_access_progress(access, progress)
        return progress

    def cancel_background(
        self,
        access: BackgroundIntelligenceJobAccess,
    ) -> BackgroundIntelligenceJobProgress:
        payload = self._call_tool(
            BACKGROUND_CANCEL_TOOL_NAME,
            {"access": access.model_dump(mode="json")},
        )
        progress = BackgroundIntelligenceJobProgress.model_validate(payload)
        _validate_access_progress(access, progress)
        return progress

    def background_result(
        self,
        access: BackgroundIntelligenceJobAccess,
        *,
        request: IntelligenceRequest,
        current_binding: WorkspaceBinding,
    ) -> IntelligenceResponse:
        _validate_access_request(access, request)
        payload = self._call_tool(
            BACKGROUND_RESULT_TOOL_NAME,
            {
                "access": access.model_dump(mode="json"),
                "current_binding": current_binding.model_dump(mode="json"),
            },
        )
        response = IntelligenceResponse.model_validate(payload)
        validation = PydanticContractGateway().validate_response(
            request=request,
            response=response,
            current_binding=current_binding,
        )
        if not validation.accepted:
            raise IntelligenceMcpProtocolError(
                "background intelligence result failed local contract validation: "
                + "; ".join(validation.reasons)
            )
        return response

    def _call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            return asyncio.run(self._call_tool_async(name, arguments))
        except IntelligenceMcpProtocolError:
            raise
        except (TimeoutError, _httpx.TimeoutException) as exc:
            raise IntelligenceMcpTimeout(
                f"Intelligence MCP HTTP request timed out: {name}"
            ) from exc
        except Exception as exc:
            raise IntelligenceMcpUnavailable(
                "Intelligence MCP HTTP service was unavailable"
            ) from exc

    async def _call_tool_async(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        transport = _httpx.AsyncHTTPTransport(
            uds=str(self.config.unix_socket),
            retries=0,
        )
        timeout = _httpx.Timeout(float(self.config.timeout_seconds))
        async with _httpx.AsyncClient(
            transport=transport,
            timeout=timeout,
            trust_env=False,
        ) as http_client:
            async with streamable_http_client(
                self.config.endpoint_url,
                http_client=http_client,
            ) as streams:
                read_stream, write_stream = streams[:2]
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    read_timeout = (
                        float(self.config.timeout_seconds)
                        if _MCP_SDK_V2
                        else timedelta(seconds=float(self.config.timeout_seconds))
                    )
                    result = await session.call_tool(
                        name,
                        arguments,
                        read_timeout_seconds=read_timeout,
                    )
        is_error = bool(
            getattr(result, "isError", getattr(result, "is_error", False))
        )
        if is_error:
            raise IntelligenceMcpProtocolError(
                _tool_error_text(result.content) or "Intelligence MCP HTTP tool failed"
            )
        structured_content = getattr(
            result,
            "structuredContent",
            getattr(result, "structured_content", None),
        )
        if isinstance(structured_content, dict):
            return structured_content
        for item in result.content:
            text = getattr(item, "text", None)
            if not isinstance(text, str):
                continue
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                return payload
        raise IntelligenceMcpProtocolError(
            "Intelligence MCP HTTP result omitted structured output"
        )


def _tool_error_text(content: list[Any]) -> str | None:
    for item in content:
        text = getattr(item, "text", None)
        if isinstance(text, str) and text:
            return text[:500]
    return None


def _validate_access_request(
    access: BackgroundIntelligenceJobAccess,
    request: IntelligenceRequest,
) -> None:
    if (
        access.request_id != request.request_id
        or access.mission_id != request.mission_id
        or access.workspace_binding != request.workspace_binding
    ):
        raise IntelligenceMcpProtocolError(
            "background intelligence job binding does not match the request"
        )


def _validate_access_progress(
    access: BackgroundIntelligenceJobAccess,
    progress: BackgroundIntelligenceJobProgress,
) -> None:
    if access != BackgroundIntelligenceJobAccess.from_progress(progress):
        raise IntelligenceMcpProtocolError(
            "background intelligence progress binding does not match the job access"
        )


__all__ = [
    "IntelligenceMcpHttpClient",
    "IntelligenceMcpHttpClientConfig",
]
