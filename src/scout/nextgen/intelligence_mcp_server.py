"""Scout-owned stdio MCP server for the isolated intelligence process."""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from pathlib import Path
from typing import Any, Protocol

from scout.nextgen.intelligence_gateway import (
    IntelligenceRequest,
    IntelligenceResponse,
    StubIntelligenceGateway,
)
from scout.nextgen.intelligence_mcp import (
    INTELLIGENCE_TOOL_NAME,
    MCP_PROTOCOL_VERSION,
    MAX_RESPONSE_BYTES,
)
from scout.nextgen.openai_compatible_backend import (
    OpenAICompatibleBackendConfig,
    build_praison_openai_compatible_runtime,
)
from scout.nextgen.praison_service import (
    EvidenceCatalog,
    PraisonAgentTeamRuntime,
    PraisonIntelligenceService,
    build_praison_model_replay_runtime,
)

SUPPORTED_PROTOCOL_VERSIONS = frozenset({"2025-11-25", MCP_PROTOCOL_VERSION})


class IntelligenceService(Protocol):
    def execute(self, request: IntelligenceRequest) -> IntelligenceResponse: ...


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scout Intelligence MCP server")
    parser.add_argument(
        "--mode",
        choices=(
            "stub",
            "praison-replay",
            "praison-model-replay",
            "praison-openai-compatible",
        ),
        default="praison-replay",
    )
    parser.add_argument("--evidence-catalog", type=Path)
    parser.add_argument("--model-runtime-config", type=Path)
    return parser


def build_service(
    *,
    mode: str,
    evidence_catalog_path: Path | None,
    model_runtime_config_path: Path | None = None,
) -> IntelligenceService:
    if mode == "stub":
        return StubIntelligenceGateway()
    catalog = (
        EvidenceCatalog.from_json_file(evidence_catalog_path)
        if evidence_catalog_path is not None
        else EvidenceCatalog()
    )
    if mode == "praison-openai-compatible":
        if model_runtime_config_path is None:
            raise ValueError(
                "praison-openai-compatible requires --model-runtime-config"
            )
        runtime = build_praison_openai_compatible_runtime(
            config=OpenAICompatibleBackendConfig.from_json_file(
                model_runtime_config_path
            )
        )
    elif mode == "praison-model-replay":
        runtime = build_praison_model_replay_runtime()
    else:
        runtime = PraisonAgentTeamRuntime()
    return PraisonIntelligenceService(
        runtime=runtime,
        evidence_catalog=catalog,
        max_concurrency=1,
    )


def serve_stdio(service: IntelligenceService) -> int:
    for line in sys.stdin:
        if len(line.encode("utf-8")) > MAX_RESPONSE_BYTES:
            _write_error(None, -32600, "MCP request exceeded the Scout size limit")
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            _write_error(None, -32700, "Invalid JSON")
            continue
        if not isinstance(message, dict):
            _write_error(None, -32600, "MCP request must be an object")
            continue
        request_id = message.get("id")
        method = message.get("method")
        params = message.get("params") or {}
        if request_id is None:
            continue
        try:
            result = _dispatch(service, str(method), params)
        except Exception:
            _write_error(request_id, -32603, "Scout Intelligence MCP internal error")
            continue
        _write({"jsonrpc": "2.0", "id": request_id, "result": result})
    return 0


def _dispatch(
    service: IntelligenceService,
    method: str,
    params: Any,
) -> dict[str, Any]:
    if method == "initialize":
        requested = params.get("protocolVersion") if isinstance(params, dict) else None
        version = (
            requested if requested in SUPPORTED_PROTOCOL_VERSIONS else MCP_PROTOCOL_VERSION
        )
        return {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {
                "name": "scout-intelligence-service",
                "version": "0.1",
            },
        }
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": [_tool_description()]}
    if method == "tools/call":
        return _call_tool(service, params)
    raise ValueError(f"unsupported MCP method: {method}")


def _call_tool(
    service: IntelligenceService,
    params: Any,
) -> dict[str, Any]:
    if not isinstance(params, dict) or params.get("name") != INTELLIGENCE_TOOL_NAME:
        return _tool_error("Scout Intelligence tool is not allowlisted")
    arguments = params.get("arguments")
    if not isinstance(arguments, dict) or "request" not in arguments:
        return _tool_error("Scout Intelligence tool requires a typed request")
    try:
        request = IntelligenceRequest.model_validate(arguments["request"])
    except Exception:
        return _tool_error("Scout Intelligence request failed schema validation")
    with contextlib.redirect_stdout(sys.stderr):
        response = service.execute(request)
    payload = response.model_dump(mode="json")
    return {
        "content": [
            {
                "type": "text",
                "text": "Candidate response is available in structuredContent.",
            }
        ],
        "structuredContent": payload,
        "isError": False,
    }


def _tool_description() -> dict[str, Any]:
    request_schema = IntelligenceRequest.model_json_schema()
    request_defs = request_schema.pop("$defs", {})
    return {
        "name": INTELLIGENCE_TOOL_NAME,
        "title": "Analyze route terrain candidates",
        "description": (
            "Analyze task-bound route and terrain evidence. Results are always "
            "candidate-only and never runtime safety truth."
        ),
        "inputSchema": {
            "type": "object",
            "$defs": request_defs,
            "properties": {"request": request_schema},
            "required": ["request"],
            "additionalProperties": False,
        },
        "outputSchema": IntelligenceResponse.model_json_schema(),
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    }


def _tool_error(message: str) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": message}],
        "isError": True,
    }


def _write_error(request_id: Any, code: int, message: str) -> None:
    _write(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": code, "message": message},
        }
    )


def _write(payload: dict[str, Any]) -> None:
    sys.stdout.write(
        json.dumps(payload, ensure_ascii=True, separators=(",", ":")) + "\n"
    )
    sys.stdout.flush()


def main() -> int:
    args = build_parser().parse_args()
    try:
        service = build_service(
            mode=args.mode,
            evidence_catalog_path=args.evidence_catalog,
            model_runtime_config_path=args.model_runtime_config,
        )
    except Exception as exc:
        print(f"Scout Intelligence Service failed to initialize: {exc}", file=sys.stderr)
        return 2
    try:
        return serve_stdio(service)
    finally:
        close_service = getattr(service, "close", None)
        if callable(close_service):
            close_service()


if __name__ == "__main__":
    raise SystemExit(main())
