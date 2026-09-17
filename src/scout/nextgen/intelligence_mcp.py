"""Process-isolated MCP transport for Scout Intelligence Service."""

from __future__ import annotations

import json
import os
import queue
import re
import shutil
import subprocess
import threading
from collections import deque
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from scout.nextgen.intelligence_gateway import (
    GatewayValidationResult,
    IntelligenceRequest,
    IntelligenceResponse,
    IntelligenceTaskType,
    PydanticContractGateway,
    WorkspaceBinding,
    degraded_intelligence_response,
)
from scout.nextgen.praison_background_mcp import (
    BackgroundIntelligenceJobAccess,
    BackgroundIntelligenceJobSubmission,
)
from scout.nextgen.praison_background_queue import (
    BackgroundIntelligenceJobProgress,
)
from scout.schemas.base import SchemaModel

MCP_PROTOCOL_VERSION = "2026-07-28"
INTELLIGENCE_TOOL_NAME = "scout_analyze_route_terrain_candidate"
DEEP_RESEARCH_TOOL_NAME = "scout_deep_research_candidate"
BACKGROUND_SUBMIT_TOOL_NAME = "scout_submit_background_intelligence_candidate"
BACKGROUND_STATUS_TOOL_NAME = "scout_get_background_intelligence_progress"
BACKGROUND_CANCEL_TOOL_NAME = "scout_cancel_background_intelligence_candidate"
BACKGROUND_RESULT_TOOL_NAME = "scout_get_background_intelligence_result"
INTELLIGENCE_TOOL_NAMES = frozenset(
    {INTELLIGENCE_TOOL_NAME, DEEP_RESEARCH_TOOL_NAME}
)
BACKGROUND_INTELLIGENCE_TOOL_NAMES = frozenset(
    {
        BACKGROUND_SUBMIT_TOOL_NAME,
        BACKGROUND_STATUS_TOOL_NAME,
        BACKGROUND_CANCEL_TOOL_NAME,
        BACKGROUND_RESULT_TOOL_NAME,
    }
)
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
_SHELL_EXECUTABLES = frozenset(
    {"sh", "bash", "zsh", "fish", "dash", "cmd", "cmd.exe", "powershell", "pwsh"}
)
_INLINE_CODE_ARGUMENTS = frozenset({"-c", "--command", "--eval", "-e"})
_CREDENTIAL_ENV_NAME_PATTERN = re.compile(r"^SCOUT_[A-Z0-9_]*(?:KEY|TOKEN)$")
_PROCESS_EXIT_CLASSIFICATION_GRACE_SECONDS = 0.1


class IntelligenceMcpError(RuntimeError):
    pass


class IntelligenceMcpCommandRejected(IntelligenceMcpError):
    pass


class IntelligenceMcpUnavailable(IntelligenceMcpError):
    pass


class IntelligenceMcpTimeout(IntelligenceMcpError):
    pass


class IntelligenceMcpProtocolError(IntelligenceMcpError):
    pass


class IntelligenceTransportStatus(StrEnum):
    OK = "ok"
    UNAVAILABLE = "unavailable"
    TIMEOUT = "timeout"
    PROTOCOL_ERROR = "protocol_error"
    RESPONSE_REJECTED = "response_rejected"


class IntelligenceGatewayExecution(SchemaModel):
    status: IntelligenceTransportStatus
    response: IntelligenceResponse
    service_reached: bool
    degraded: bool
    failure_reason: str | None = None
    remote_validation: GatewayValidationResult | None = None
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False


@dataclass(frozen=True)
class IntelligenceMcpClientConfig:
    command: tuple[str, ...]
    timeout_seconds: float = 30.0
    startup_timeout_seconds: float = 30.0
    pythonpath: str | None = None
    credential_env_names: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.command or not all(
            isinstance(item, str) and item for item in self.command
        ):
            raise IntelligenceMcpCommandRejected(
                "Intelligence MCP command must be a non-empty argument list"
            )
        executable = Path(self.command[0]).name.casefold()
        if executable in _SHELL_EXECUTABLES:
            raise IntelligenceMcpCommandRejected(
                "Shell executables are forbidden for Intelligence MCP transport"
            )
        if any(
            argument.casefold() in _INLINE_CODE_ARGUMENTS
            for argument in self.command[1:]
        ):
            raise IntelligenceMcpCommandRejected(
                "Inline code execution is forbidden for Intelligence MCP transport"
            )
        if not 0.25 <= float(self.timeout_seconds) <= 300:
            raise ValueError("Intelligence MCP timeout must be between 0.25 and 300 seconds")
        if not 0.25 <= float(self.startup_timeout_seconds) <= 300:
            raise ValueError(
                "Intelligence MCP startup timeout must be between 0.25 and 300 seconds"
            )
        if len(self.credential_env_names) != len(set(self.credential_env_names)):
            raise IntelligenceMcpCommandRejected(
                "Intelligence MCP credential environment names must be unique"
            )
        if any(
            not _CREDENTIAL_ENV_NAME_PATTERN.fullmatch(name)
            for name in self.credential_env_names
        ):
            raise IntelligenceMcpCommandRejected(
                "Intelligence MCP credentials must use Scout-owned KEY/TOKEN names"
            )


class IntelligenceMcpStdioClient:
    """Single-process stdio MCP client with a bounded tool allowlist."""

    def __init__(self, config: IntelligenceMcpClientConfig) -> None:
        self.config = config
        self._process: subprocess.Popen[str] | None = None
        self._responses: queue.Queue[dict[str, Any] | BaseException] = queue.Queue()
        self._stderr: deque[str] = deque(maxlen=20)
        self._reader: threading.Thread | None = None
        self._stderr_reader: threading.Thread | None = None
        self._lock = threading.RLock()
        self._request_id = 0
        self._initialized = False

    def __enter__(self) -> "IntelligenceMcpStdioClient":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def initialize(self) -> None:
        with self._lock:
            if self._initialized:
                return
            self._start()
            result = self._rpc(
                "initialize",
                {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {
                        "name": "scout-core-intelligence-gateway",
                        "version": "0.1",
                    },
                },
                timeout_seconds=self.config.startup_timeout_seconds,
            )
            if not isinstance(result, dict) or not result.get("serverInfo"):
                raise IntelligenceMcpProtocolError(
                    "Intelligence MCP initialize response was invalid"
                )
            self._notify("notifications/initialized", {})
            self._initialized = True

    def call(self, request: IntelligenceRequest) -> IntelligenceResponse:
        payload = self._call_tool(
            _tool_name_for_request(request),
            {"request": request.model_dump(mode="json")},
        )
        return IntelligenceResponse.model_validate(payload)

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
        with self._lock:
            self.initialize()
            result = self._rpc(
                "tools/call",
                {"name": name, "arguments": arguments},
            )
        if not isinstance(result, dict):
            raise IntelligenceMcpProtocolError(
                "Intelligence MCP tool result was not an object"
            )
        if result.get("isError"):
            raise IntelligenceMcpProtocolError(
                _tool_error_message(result) or "Intelligence MCP tool failed"
            )
        structured = result.get("structuredContent")
        if isinstance(structured, dict):
            return structured
        content = result.get("content")
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    try:
                        payload = json.loads(str(item.get("text", "")))
                    except json.JSONDecodeError:
                        continue
                    if isinstance(payload, dict):
                        return payload
        raise IntelligenceMcpProtocolError(
            "Intelligence MCP result omitted structured output"
        )

    def close(self) -> None:
        with self._lock:
            process = self._process
            self._initialized = False
            if process is None:
                return
            if process.stdin is not None:
                try:
                    process.stdin.close()
                except OSError:
                    pass
            if process.poll() is None:
                try:
                    process.terminate()
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
            # Reap the readers before replacing their response queue or dropping
            # the Popen streams. Thread exit owns closing stdout and stderr.
            readers = (self._reader, self._stderr_reader)
            for reader in readers:
                if reader is not None:
                    reader.join(timeout=2)
            if any(reader is not None and reader.is_alive() for reader in readers):
                raise IntelligenceMcpUnavailable(
                    "Intelligence MCP pipe readers did not stop after process exit"
                )
            for stream in (process.stdout, process.stderr):
                if stream is not None:
                    stream.close()
            self._reader = None
            self._stderr_reader = None
            self._process = None

    def _start(self) -> None:
        if self._process is not None:
            if self._process.poll() is None:
                return
            self.close()
        executable = self.config.command[0]
        resolved = executable if Path(executable).is_absolute() else shutil.which(executable)
        if not resolved:
            raise IntelligenceMcpUnavailable(
                f"Intelligence MCP executable is unavailable: {executable}"
            )
        command = (str(resolved), *self.config.command[1:])
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                bufsize=1,
                shell=False,
                env=self._subprocess_env(),
            )
        except OSError as exc:
            raise IntelligenceMcpUnavailable(
                "Intelligence MCP process could not start"
            ) from exc
        self._process = process
        self._responses = queue.Queue()
        self._reader = threading.Thread(
            target=self._read_stdout,
            args=(process,),
            daemon=True,
        )
        self._stderr_reader = threading.Thread(
            target=self._read_stderr,
            args=(process,),
            daemon=True,
        )
        self._reader.start()
        self._stderr_reader.start()

    def _subprocess_env(self) -> dict[str, str]:
        allowed = {"HOME", "PATH", "TMPDIR", "LANG", "LC_ALL"}
        env = {key: value for key, value in os.environ.items() if key in allowed}
        env.setdefault("PATH", os.defpath)
        env["PRAISONAI_TELEMETRY_DISABLED"] = "true"
        if self.config.pythonpath:
            env["PYTHONPATH"] = self.config.pythonpath
        for name in self.config.credential_env_names:
            value = os.environ.get(name)
            if value:
                env[name] = value
        return env

    def _rpc(
        self,
        method: str,
        params: dict[str, Any],
        *,
        timeout_seconds: float | None = None,
    ) -> Any:
        process = self._process
        if process is None or process.stdin is None:
            raise IntelligenceMcpUnavailable("Intelligence MCP process is not running")
        self._request_id += 1
        request_id = self._request_id
        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        }
        try:
            process.stdin.write(
                json.dumps(payload, ensure_ascii=True, separators=(",", ":")) + "\n"
            )
            process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise IntelligenceMcpUnavailable(
                "Intelligence MCP process closed its input"
            ) from exc
        try:
            response = self._responses.get(
                timeout=float(
                    self.config.timeout_seconds
                    if timeout_seconds is None
                    else timeout_seconds
                )
            )
        except queue.Empty as exc:
            try:
                process.wait(timeout=_PROCESS_EXIT_CLASSIFICATION_GRACE_SECONDS)
            except subprocess.TimeoutExpired:
                pass
            else:
                raise IntelligenceMcpUnavailable(
                    "Intelligence MCP process exited before responding"
                ) from exc
            raise IntelligenceMcpTimeout(
                f"Intelligence MCP request timed out: {method}"
            ) from exc
        if isinstance(response, BaseException):
            raise response
        if response.get("id") != request_id:
            raise IntelligenceMcpProtocolError(
                "Intelligence MCP response id did not match request"
            )
        if isinstance(response.get("error"), dict):
            raise IntelligenceMcpProtocolError(
                str(response["error"].get("message") or "Intelligence MCP RPC error")
            )
        if "result" not in response:
            raise IntelligenceMcpProtocolError(
                "Intelligence MCP response omitted result"
            )
        return response["result"]

    def _notify(self, method: str, params: dict[str, Any]) -> None:
        process = self._process
        if process is None or process.stdin is None:
            raise IntelligenceMcpUnavailable("Intelligence MCP process is not running")
        process.stdin.write(
            json.dumps(
                {"jsonrpc": "2.0", "method": method, "params": params},
                ensure_ascii=True,
                separators=(",", ":"),
            )
            + "\n"
        )
        process.stdin.flush()

    def _read_stdout(self, process: subprocess.Popen[str]) -> None:
        if process.stdout is None:
            self._responses.put(
                IntelligenceMcpUnavailable("Intelligence MCP stdout is unavailable")
            )
            return
        try:
            for line in process.stdout:
                if len(line.encode("utf-8")) > MAX_RESPONSE_BYTES:
                    self._responses.put(
                        IntelligenceMcpProtocolError(
                            "Intelligence MCP response exceeded size limit"
                        )
                    )
                    return
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    self._responses.put(
                        IntelligenceMcpProtocolError(
                            "Intelligence MCP stdout contained non-protocol output"
                        )
                    )
                    return
                if isinstance(value, dict) and value.get("id") is not None:
                    self._responses.put(value)
        finally:
            process.stdout.close()
            if self._process is process:
                code = process.poll()
                self._responses.put(
                    IntelligenceMcpUnavailable(
                        f"Intelligence MCP process exited before responding (code={code})"
                    )
                )

    def _read_stderr(self, process: subprocess.Popen[str]) -> None:
        if process.stderr is None:
            return
        try:
            for line in process.stderr:
                value = " ".join(line.strip().split())
                if value:
                    self._stderr.append(value[:500])
        finally:
            process.stderr.close()


class McpIntelligenceGateway:
    """Resilient Scout Core facade around the untrusted MCP service."""

    def __init__(self, config: IntelligenceMcpClientConfig) -> None:
        self.client = IntelligenceMcpStdioClient(config)
        self.contract_gateway = PydanticContractGateway()

    def __enter__(self) -> "McpIntelligenceGateway":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def close(self) -> None:
        self.client.close()

    def execute(
        self,
        request: IntelligenceRequest,
        *,
        current_binding: WorkspaceBinding | None = None,
    ) -> IntelligenceGatewayExecution:
        try:
            response = self.client.call(request)
        except IntelligenceMcpTimeout:
            self.client.close()
            return self._transport_degraded(
                request,
                IntelligenceTransportStatus.TIMEOUT,
                "intelligence MCP request timed out",
            )
        except IntelligenceMcpUnavailable:
            self.client.close()
            return self._transport_degraded(
                request,
                IntelligenceTransportStatus.UNAVAILABLE,
                "intelligence MCP service was unavailable",
            )
        except Exception:
            self.client.close()
            return self._transport_degraded(
                request,
                IntelligenceTransportStatus.PROTOCOL_ERROR,
                "intelligence MCP response failed protocol or schema validation",
            )
        validation = self.contract_gateway.validate_response(
            request=request,
            response=response,
            current_binding=current_binding,
        )
        if not validation.accepted:
            fallback = degraded_intelligence_response(
                request=request,
                uncertainty_id="intelligence_response_rejected",
                description="Scout Core rejected the intelligence candidate.",
                missing_evidence=("valid_fresh_intelligence_response",),
                impact="the untrusted candidate was discarded",
                recommended_next_evidence=("retry_with_current_workspace_binding",),
                service_name="scout.mcp_intelligence_gateway",
                service_version="0.1",
                agent_path=("mcp", "pydantic_contract_gateway", "rejected"),
            )
            return IntelligenceGatewayExecution(
                status=IntelligenceTransportStatus.RESPONSE_REJECTED,
                response=fallback,
                service_reached=True,
                degraded=True,
                failure_reason="; ".join(validation.reasons),
                remote_validation=validation,
            )
        return IntelligenceGatewayExecution(
            status=IntelligenceTransportStatus.OK,
            response=response,
            service_reached=True,
            degraded=bool(response.uncertainties and not response.findings),
            remote_validation=validation,
        )

    @staticmethod
    def _transport_degraded(
        request: IntelligenceRequest,
        status: IntelligenceTransportStatus,
        reason: str,
    ) -> IntelligenceGatewayExecution:
        response = degraded_intelligence_response(
            request=request,
            uncertainty_id="intelligence_transport_unavailable",
            description=reason,
            missing_evidence=("reachable_intelligence_mcp_service",),
            impact="candidate intelligence was not produced",
            recommended_next_evidence=("retry_intelligence_service",),
            service_name="scout.mcp_intelligence_gateway",
            service_version="0.1",
            agent_path=("mcp", "degraded"),
        )
        return IntelligenceGatewayExecution(
            status=status,
            response=response,
            service_reached=False,
            degraded=True,
            failure_reason=reason,
        )


def _tool_error_message(result: dict[str, Any]) -> str | None:
    content = result.get("content")
    if not isinstance(content, list):
        return None
    for item in content:
        if isinstance(item, dict) and item.get("type") == "text":
            text = item.get("text")
            if isinstance(text, str) and text:
                return text[:500]
    return None


def _tool_name_for_request(request: IntelligenceRequest) -> str:
    if request.task_type is IntelligenceTaskType.DEEP_RESEARCH:
        return DEEP_RESEARCH_TOOL_NAME
    return INTELLIGENCE_TOOL_NAME


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
    expected = BackgroundIntelligenceJobAccess.from_progress(progress)
    if access != expected:
        raise IntelligenceMcpProtocolError(
            "background intelligence progress binding does not match the job access"
        )


__all__ = [
    "BACKGROUND_CANCEL_TOOL_NAME",
    "BACKGROUND_INTELLIGENCE_TOOL_NAMES",
    "BACKGROUND_RESULT_TOOL_NAME",
    "BACKGROUND_STATUS_TOOL_NAME",
    "BACKGROUND_SUBMIT_TOOL_NAME",
    "DEEP_RESEARCH_TOOL_NAME",
    "INTELLIGENCE_TOOL_NAME",
    "INTELLIGENCE_TOOL_NAMES",
    "IntelligenceGatewayExecution",
    "IntelligenceMcpClientConfig",
    "IntelligenceMcpCommandRejected",
    "IntelligenceMcpError",
    "IntelligenceMcpProtocolError",
    "IntelligenceMcpStdioClient",
    "IntelligenceMcpTimeout",
    "IntelligenceMcpUnavailable",
    "IntelligenceTransportStatus",
    "McpIntelligenceGateway",
]
