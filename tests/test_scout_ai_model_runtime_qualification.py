from __future__ import annotations

import importlib.util
import json
import os
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from scout.nextgen.intelligence_mcp import (
    IntelligenceMcpClientConfig,
    IntelligenceMcpCommandRejected,
    IntelligenceMcpStdioClient,
)
from scout.nextgen.model_qualification import (
    ModelQualificationDisposition,
    ModelQualificationStatus,
    ModelRuntimeQualificationReport,
    TOOL_CALLING_EVIDENCE_REF,
    TOOL_CALLING_OUTPUT_MARKER,
    TOOL_CALLING_PROBE_NAME,
    apply_model_capability_attestation,
    build_model_capability_attestation,
    qualification_report_hash,
    run_openai_compatible_qualification,
)
from scout.nextgen.model_runtime import (
    ModelCapabilityAttestation,
    ModelRuntimeCapability,
)
from scout.nextgen.openai_compatible_backend import OpenAICompatibleBackendConfig
from scout.nextgen.praison_service import (
    SPECIALIST_INPUT_MARKER,
    SpecialistModelInput,
    replay_specialist_report,
)


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
FIXTURES = Path(__file__).parent / "fixtures" / "nextgen"
CASE_PATH = FIXTURES / "model_runtime_qualification_case.json"
EVIDENCE_PATH = FIXTURES / "model_runtime_qualification_evidence.json"
PRAISON_AVAILABLE = importlib.util.find_spec("praisonaiagents") is not None


class _ServerState:
    def __init__(self, *, observed_model_id: str | None = None) -> None:
        self.observed_model_id = observed_model_id
        self.requests: list[dict[str, Any]] = []
        self.lock = threading.Lock()


@contextmanager
def _qualification_server(
    *,
    observed_model_id: str | None = None,
    delay_seconds: float = 0,
    tool_calling_supported: bool = True,
) -> Iterator[tuple[str, _ServerState]]:
    state = _ServerState(observed_model_id=observed_model_id)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self) -> None:  # noqa: N802 - stdlib handler contract
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length))
            with state.lock:
                state.requests.append(payload)
            if delay_seconds:
                time.sleep(delay_seconds)
            tools = payload.get("tools") or []
            tool_names = {
                tool["function"]["name"]
                for tool in tools
                if isinstance(tool, dict) and isinstance(tool.get("function"), dict)
            }
            has_tool_result = any(
                message.get("role") == "tool"
                for message in payload.get("messages", [])
                if isinstance(message, dict)
            )
            if TOOL_CALLING_PROBE_NAME in tool_names and tool_calling_supported:
                if has_tool_result:
                    message = {
                        "role": "assistant",
                        "content": TOOL_CALLING_OUTPUT_MARKER,
                    }
                    finish_reason = "stop"
                else:
                    message = {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call-scout-tool-qualification",
                                "type": "function",
                                "function": {
                                    "name": TOOL_CALLING_PROBE_NAME,
                                    "arguments": json.dumps(
                                        {"evidence_ref": TOOL_CALLING_EVIDENCE_REF}
                                    ),
                                },
                            }
                        ],
                    }
                    finish_reason = "tool_calls"
            elif TOOL_CALLING_PROBE_NAME in tool_names:
                message = {
                    "role": "assistant",
                    "content": TOOL_CALLING_OUTPUT_MARKER,
                }
                finish_reason = "stop"
            elif tools:
                arguments = _tool_arguments(payload)
                message = {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call-scout-qualification",
                            "type": "function",
                            "function": {
                                "name": tools[0]["function"]["name"],
                                "arguments": json.dumps(arguments),
                            },
                        }
                    ],
                }
                finish_reason = "tool_calls"
            else:
                message = {
                    "role": "assistant",
                    "content": "SCOUT_BASIC_CHAT_OK",
                }
                finish_reason = "stop"
            body = {
                "id": "chatcmpl-scout-qualification",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": state.observed_model_id or payload["model"],
                "choices": [
                    {
                        "index": 0,
                        "message": message,
                        "finish_reason": finish_reason,
                    }
                ],
                "usage": {
                    "prompt_tokens": 19,
                    "completion_tokens": 6,
                    "total_tokens": 25,
                },
            }
            encoded = json.dumps(body).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            try:
                self.wfile.write(encoded)
            except BrokenPipeError:
                pass

        def log_message(self, format: str, *args: Any) -> None:
            del format, args

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}/v1", state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _tool_arguments(payload: dict[str, Any]) -> dict[str, Any]:
    for message in reversed(payload["messages"]):
        content = message.get("content")
        if isinstance(content, str) and SPECIALIST_INPUT_MARKER in content:
            model_input = SpecialistModelInput.model_validate_json(
                content.split(SPECIALIST_INPUT_MARKER, 1)[1].strip()
            )
            return replay_specialist_report(model_input).model_dump(mode="json")
    return {
        "marker": "SCOUT_TYPED_OUTPUT_OK",
        "candidate_only": True,
        "runtime_safety_truth": False,
    }


def _runtime_config(
    tmp_path: Path,
    base_url: str,
    *,
    accepted_observed_model_ids: list[str] | None = None,
) -> Path:
    path = tmp_path / "runtime.json"
    path.write_text(
        json.dumps(
            {
                "runtime_id": "qualification.local.http",
                "provider": "qualification-replay",
                "model_id": "qualification-requested-model",
                "base_url": base_url,
                "transport_scope": "loopback",
                "tier": "local_fast",
                "locality": "edge",
                "accelerator": "cpu",
                "context_limit_tokens": 8192,
                "max_concurrency": 1,
                "offline_capable": True,
                "privacy_preserving": True,
                "accepted_observed_model_ids": accepted_observed_model_ids or [],
                "experimental": True,
                "candidate_only": True,
                "runtime_safety_truth": False,
            }
        ),
        encoding="utf-8",
    )
    return path


def _qualification_case_with_timeout(
    tmp_path: Path,
    *,
    timeout_seconds: float,
) -> Path:
    payload = json.loads(CASE_PATH.read_text(encoding="utf-8"))
    payload["timeout_seconds"] = timeout_seconds
    path = tmp_path / "qualification-case.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _unused_loopback_base_url() -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    return f"http://127.0.0.1:{port}/v1"


def _checks(report: ModelRuntimeQualificationReport) -> dict[str, Any]:
    return {check.check_id: check for check in report.checks}


def test_mcp_forwards_only_explicit_scout_model_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SCOUT_QUALIFICATION_MODEL_KEY", "selected-secret")
    monkeypatch.setenv("UNRELATED_SECRET", "must-not-cross-boundary")
    config = IntelligenceMcpClientConfig(
        command=(sys.executable, "-m", "scout.nextgen.intelligence_mcp_server"),
        credential_env_names=("SCOUT_QUALIFICATION_MODEL_KEY",),
    )

    child_env = IntelligenceMcpStdioClient(config)._subprocess_env()

    assert child_env["SCOUT_QUALIFICATION_MODEL_KEY"] == "selected-secret"
    assert "UNRELATED_SECRET" not in child_env


@pytest.mark.parametrize(
    "name",
    ["OPENAI_API_KEY", "SCOUT_MODEL_PASSWORD", "SCOUT_MODEL_KEY=value"],
)
def test_mcp_rejects_non_scout_or_malformed_credential_names(name: str) -> None:
    with pytest.raises(IntelligenceMcpCommandRejected):
        IntelligenceMcpClientConfig(
            command=(sys.executable, "-m", "scout.nextgen.intelligence_mcp_server"),
            credential_env_names=(name,),
        )


def test_independent_tool_calling_qualification_executes_one_read_only_tool(
    tmp_path: Path,
) -> None:
    runtime_config_path: Path
    with _qualification_server() as (base_url, state):
        runtime_config_path = _runtime_config(tmp_path, base_url)
        report = run_openai_compatible_qualification(
            runtime_config_path=runtime_config_path,
            case_path=CASE_PATH,
            evidence_catalog_path=EVIDENCE_PATH,
            python_executable=sys.executable,
            pythonpath=str(SRC),
            stop_after="tool_calling",
        )

    checks = _checks(report)
    tool_check = checks["tool_calling"]
    assert report.schema_version == "scout.model_runtime_qualification.v1"
    assert report.experiment_id == "SCOUT-AI-EXP-MODEL-RUNTIME-QUAL-005"
    assert report.disposition is ModelQualificationDisposition.PARTIAL
    assert tool_check.status is ModelQualificationStatus.PASSED
    assert tool_check.tool_call_count == 1
    assert tool_check.tools_called == (TOOL_CALLING_PROBE_NAME,)
    assert tool_check.model_request_count == 2
    assert checks["praison_mcp"].status is ModelQualificationStatus.NOT_RUN
    assert len(state.requests) == 4
    assert TOOL_CALLING_PROBE_NAME in {
        tool["function"]["name"]
        for tool in state.requests[2]["tools"]
    }
    attestation = build_model_capability_attestation(report)
    assert attestation.capabilities == frozenset(
        {ModelRuntimeCapability.TOOL_CALLING}
    )
    profile = apply_model_capability_attestation(
        config=OpenAICompatibleBackendConfig.from_json_file(runtime_config_path),
        runtime_config_path=runtime_config_path,
        attestation=attestation,
    )
    assert ModelRuntimeCapability.TOOL_CALLING in profile.capabilities
    assert profile.capability_attestation_refs == (report.report_hash,)

    expired = attestation.model_copy(
        update={
            "qualified_at": datetime.now(UTC) - timedelta(hours=2),
            "expires_at": datetime.now(UTC) - timedelta(hours=1),
        }
    )
    with pytest.raises(ValueError, match="expired"):
        apply_model_capability_attestation(
            config=OpenAICompatibleBackendConfig.from_json_file(
                runtime_config_path
            ),
            runtime_config_path=runtime_config_path,
            attestation=expired,
        )

    altered_runtime_path = tmp_path / "runtime-altered.json"
    altered_runtime_path.write_text(
        runtime_config_path.read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="config hash mismatch"):
        apply_model_capability_attestation(
            config=OpenAICompatibleBackendConfig.from_json_file(
                altered_runtime_path
            ),
            runtime_config_path=altered_runtime_path,
            attestation=attestation,
        )

    tampered_report = report.model_copy(update={"report_hash": "0" * 64})
    with pytest.raises(ValueError, match="report hash"):
        build_model_capability_attestation(tampered_report)


def test_qualification_cli_can_stop_after_independent_tool_calling(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "tool-calling-qualification.json"
    attestation_path = tmp_path / "tool-calling-attestation.json"
    with _qualification_server() as (base_url, state):
        completed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools" / "scout_ai_model_runtime_qualification.py"),
                "--runtime-config",
                str(_runtime_config(tmp_path, base_url)),
                "--case",
                str(CASE_PATH),
                "--evidence-catalog",
                str(EVIDENCE_PATH),
                "--output",
                str(output_path),
                "--pythonpath",
                str(SRC),
                "--stop-after",
                "tool_calling",
                "--capability-attestation-output",
                str(attestation_path),
            ],
            cwd=ROOT,
            env={
                "HOME": os.environ.get("HOME", ""),
                "PATH": os.environ.get("PATH", os.defpath),
                "PYTHONPATH": str(SRC),
            },
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )

    assert completed.returncode == 5
    report = ModelRuntimeQualificationReport.model_validate_json(
        output_path.read_bytes()
    )
    checks = _checks(report)
    assert report.disposition is ModelQualificationDisposition.PARTIAL
    assert checks["tool_calling"].status is ModelQualificationStatus.PASSED
    assert checks["praison_mcp"].status is ModelQualificationStatus.NOT_RUN
    assert len(state.requests) == 4
    attestation = ModelCapabilityAttestation.model_validate_json(
        attestation_path.read_bytes()
    )
    assert attestation.qualification_report_hash == report.report_hash
    assert attestation.capabilities == frozenset(
        {ModelRuntimeCapability.TOOL_CALLING}
    )


def test_independent_tool_calling_qualification_rejects_marker_without_tool(
    tmp_path: Path,
) -> None:
    with _qualification_server(tool_calling_supported=False) as (base_url, _):
        report = run_openai_compatible_qualification(
            runtime_config_path=_runtime_config(tmp_path, base_url),
            case_path=CASE_PATH,
            evidence_catalog_path=EVIDENCE_PATH,
            python_executable=sys.executable,
            pythonpath=str(SRC),
            stop_after="tool_calling",
        )

    checks = _checks(report)
    assert report.disposition is ModelQualificationDisposition.FAILED
    assert checks["tool_calling"].status is ModelQualificationStatus.FAILED
    assert checks["tool_calling"].tool_call_count == 0
    assert checks["tool_calling"].error_type == "ToolCallingProbeNotExecuted"
    assert checks["praison_mcp"].status is ModelQualificationStatus.NOT_RUN
    with pytest.raises(ValueError, match="not independently qualified"):
        build_model_capability_attestation(report)


@pytest.mark.skipif(not PRAISON_AVAILABLE, reason="optional PraisonAI is unavailable")
def test_live_qualification_runs_basic_typed_and_praison_mcp_checks(
    tmp_path: Path,
) -> None:
    with _qualification_server() as (base_url, state):
        report = run_openai_compatible_qualification(
            runtime_config_path=_runtime_config(tmp_path, base_url),
            case_path=CASE_PATH,
            evidence_catalog_path=EVIDENCE_PATH,
            python_executable=sys.executable,
            pythonpath=str(SRC),
        )

    checks = _checks(report)
    assert report.disposition is ModelQualificationDisposition.PASSED
    assert checks["basic_chat"].status is ModelQualificationStatus.PASSED
    assert checks["typed_output"].status is ModelQualificationStatus.PASSED
    assert checks["tool_calling"].status is ModelQualificationStatus.PASSED
    assert checks["praison_mcp"].status is ModelQualificationStatus.PASSED
    assert checks["authority_boundary"].status is ModelQualificationStatus.PASSED
    assert len(state.requests) == 5
    assert state.requests[0].get("tools") is None
    assert all(request.get("tools") for request in state.requests[1:])
    assert report.intelligence_execution is not None
    assert report.intelligence_execution.response.candidate_only is True
    assert report.intelligence_execution.response.runtime_safety_truth is False
    assert {
        record.observed_model_id
        for record in report.intelligence_execution.response.provenance.model_execution_records
    } == {"qualification-requested-model"}
    assert len(
        report.intelligence_execution.response.provenance.model_execution_records
    ) == 1
    assert report.intelligence_execution.response.provenance.agent_path == (
        "praisonai.orchestrator",
        "praisonai.router.deterministic.v1",
        "terrain",
        "qgis.deterministic",
    )
    assert qualification_report_hash(report) == report.report_hash


def test_live_qualification_reports_unavailable_without_claiming_model_success(
    tmp_path: Path,
) -> None:
    report = run_openai_compatible_qualification(
        runtime_config_path=_runtime_config(tmp_path, _unused_loopback_base_url()),
        case_path=CASE_PATH,
        evidence_catalog_path=EVIDENCE_PATH,
        python_executable=sys.executable,
        pythonpath=str(SRC),
    )

    checks = _checks(report)
    assert report.disposition is ModelQualificationDisposition.UNAVAILABLE
    assert checks["configuration"].status is ModelQualificationStatus.PASSED
    assert checks["basic_chat"].status is ModelQualificationStatus.UNAVAILABLE
    assert checks["typed_output"].status is ModelQualificationStatus.NOT_RUN
    assert checks["tool_calling"].status is ModelQualificationStatus.NOT_RUN
    assert checks["praison_mcp"].status is ModelQualificationStatus.NOT_RUN
    assert report.intelligence_execution is None
    assert report.candidate_only is True
    assert report.runtime_safety_truth is False
    assert qualification_report_hash(report) == report.report_hash


def test_live_qualification_distinguishes_timeout_from_unavailable(
    tmp_path: Path,
) -> None:
    with _qualification_server(delay_seconds=0.5) as (base_url, _):
        report = run_openai_compatible_qualification(
            runtime_config_path=_runtime_config(tmp_path, base_url),
            case_path=_qualification_case_with_timeout(
                tmp_path,
                timeout_seconds=0.25,
            ),
            evidence_catalog_path=EVIDENCE_PATH,
            python_executable=sys.executable,
            pythonpath=str(SRC),
        )

    checks = _checks(report)
    assert report.disposition is ModelQualificationDisposition.TIMED_OUT
    assert checks["basic_chat"].status is ModelQualificationStatus.TIMED_OUT
    assert checks["typed_output"].status is ModelQualificationStatus.NOT_RUN
    assert checks["tool_calling"].status is ModelQualificationStatus.NOT_RUN


def test_live_qualification_fails_closed_on_unexpected_observed_model(
    tmp_path: Path,
) -> None:
    with _qualification_server(observed_model_id="unexpected-served-model") as (
        base_url,
        _,
    ):
        report = run_openai_compatible_qualification(
            runtime_config_path=_runtime_config(tmp_path, base_url),
            case_path=CASE_PATH,
            evidence_catalog_path=EVIDENCE_PATH,
            python_executable=sys.executable,
            pythonpath=str(SRC),
        )

    assert report.disposition is ModelQualificationDisposition.FAILED
    assert _checks(report)["basic_chat"].status is ModelQualificationStatus.FAILED
    assert _checks(report)["typed_output"].status is ModelQualificationStatus.NOT_RUN


def test_live_qualification_accepts_explicit_observed_model_alias(
    tmp_path: Path,
) -> None:
    with _qualification_server(observed_model_id="served-model-alias") as (
        base_url,
        _,
    ):
        report = run_openai_compatible_qualification(
            runtime_config_path=_runtime_config(
                tmp_path,
                base_url,
                accepted_observed_model_ids=["served-model-alias"],
            ),
            case_path=CASE_PATH,
            evidence_catalog_path=EVIDENCE_PATH,
            python_executable=sys.executable,
            pythonpath=str(SRC),
            stop_after="basic_chat",
        )

    assert report.disposition is ModelQualificationDisposition.PARTIAL
    assert _checks(report)["basic_chat"].status is ModelQualificationStatus.PASSED


def test_qualification_report_authority_flags_cannot_be_promoted(
    tmp_path: Path,
) -> None:
    report = run_openai_compatible_qualification(
        runtime_config_path=_runtime_config(tmp_path, _unused_loopback_base_url()),
        case_path=CASE_PATH,
        evidence_catalog_path=EVIDENCE_PATH,
        python_executable=sys.executable,
        pythonpath=str(SRC),
    )
    payload = report.model_dump(mode="json")
    payload["runtime_safety_truth"] = True

    with pytest.raises(ValidationError):
        ModelRuntimeQualificationReport.model_validate(payload)


def test_qualification_cli_writes_unavailable_report(tmp_path: Path) -> None:
    output_path = tmp_path / "qualification.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "scout_ai_model_runtime_qualification.py"),
            "--runtime-config",
            str(_runtime_config(tmp_path, _unused_loopback_base_url())),
            "--case",
            str(CASE_PATH),
            "--evidence-catalog",
            str(EVIDENCE_PATH),
            "--output",
            str(output_path),
            "--pythonpath",
            str(SRC),
        ],
        cwd=ROOT,
        env={
            "HOME": os.environ.get("HOME", ""),
            "PATH": os.environ.get("PATH", os.defpath),
            "PYTHONPATH": str(SRC),
        },
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert completed.returncode == 3
    report = ModelRuntimeQualificationReport.model_validate_json(
        output_path.read_bytes()
    )
    assert report.disposition is ModelQualificationDisposition.UNAVAILABLE
    assert "qualification.local.http" in completed.stdout
