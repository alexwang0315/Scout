from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Callable, Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field

from runtime_observation_envelope import build_signed_runtime_observation_envelope


class RuntimeStreamSignedSampleStatus(StrEnum):
    DRY_RUN_READY = "dry_run_ready"
    SENT = "sent"
    BLOCKED = "sample_blocked"
    TRANSPORT_ERROR = "transport_error"


class RuntimeStreamSignedSampleModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RuntimeStreamSignedSampleBoundary(RuntimeStreamSignedSampleModel):
    operator_initiated: Literal[True] = True
    explicit_send_required: Literal[True] = True
    raw_payloads_embedded: Literal[False] = False
    secret_values_embedded: Literal[False] = False
    endpoint_secret_embedded: Literal[False] = False
    phase2_writeback_allowed: Literal[False] = False
    incident_bridge_enable_allowed: Literal[False] = False


class RuntimeStreamSignedSampleResult(RuntimeStreamSignedSampleModel):
    artifact_kind: Literal["runtime_stream_signed_http_push_sample_result"] = (
        "runtime_stream_signed_http_push_sample_result"
    )
    status: RuntimeStreamSignedSampleStatus
    base_url: str
    endpoint_path: Literal["/runtime/streams/http-push/observations"] = (
        "/runtime/streams/http-push/observations"
    )
    source_id: str
    source_kind: str
    transport: Literal["http_push"] = "http_push"
    device_id: str
    sequence_no: int = Field(ge=0)
    observed_at: str
    payload_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    envelope_id: str | None = None
    dedupe_key: str | None = None
    request_body_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    network_send_attempted: bool
    send_performed: bool
    http_status_code: int | None = None
    response_body_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    response_status: str | None = None
    response_admission_status: str | None = None
    response_transport_surface: str | None = None
    response_ingest_surface: str | None = None
    response_admission_transport: str | None = None
    observations_accepted: int | None = Field(default=None, ge=0)
    safety_level: str | None = None
    blocker_count: int = 0
    blocker_reasons: list[str] = Field(default_factory=list)
    error_summary: str | None = None
    boundary: RuntimeStreamSignedSampleBoundary = Field(
        default_factory=RuntimeStreamSignedSampleBoundary
    )

    def to_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True
        ) + "\n"


@dataclass(frozen=True)
class RuntimeStreamHttpResponse:
    status_code: int
    response_body: str


@dataclass(frozen=True)
class RuntimeStreamHttpRequest:
    endpoint_url: str
    body: dict[str, Any]
    timeout_seconds: float


def run_runtime_stream_signed_sample(
    *,
    base_url: str,
    payload: dict[str, Any],
    secret_key: str | None,
    source_id: str = "runtime_source.apple_watch.v0",
    source_kind: str = "apple_watch",
    device_id: str = "operator.sample.watch",
    sequence_no: int = 1,
    observed_at: str = "2026-05-20T00:00:00+08:00",
    received_at: str = "2026-05-20T00:00:00+08:00",
    device: str = "apple_watch",
    source: str = "runtime_http_push_sample",
    send: bool = False,
    timeout_seconds: float = 10.0,
    transport: Callable[[RuntimeStreamHttpRequest], Any] | None = None,
) -> RuntimeStreamSignedSampleResult:
    normalized_base_url = base_url.rstrip("/")
    blockers: list[str] = []
    if not secret_key:
        blockers.append("missing_admission_secret")
    if not isinstance(payload, dict):
        blockers.append("payload_must_be_json_object")
    if blockers:
        return _result(
            status=RuntimeStreamSignedSampleStatus.BLOCKED,
            base_url=normalized_base_url,
            source_id=source_id,
            source_kind=source_kind,
            device_id=device_id,
            sequence_no=sequence_no,
            observed_at=observed_at,
            blockers=blockers,
            network_send_attempted=False,
            send_performed=False,
        )

    envelope = build_signed_runtime_observation_envelope(
        payload,
        secret_key=secret_key or "",
        envelope_id=f"runtime_stream_signed_sample.{sequence_no:04d}",
        source_id=source_id,
        source_kind=source_kind,
        transport="http_push",
        device_id=device_id,
        sequence_no=sequence_no,
        observed_at=observed_at,
        received_at=received_at,
    )
    body = {
        "envelope": envelope.model_dump(mode="json"),
        "payload": payload,
        "device": device,
        "source": source,
    }
    request_body_sha256 = _sha256_json(body)
    if not send:
        return _result(
            status=RuntimeStreamSignedSampleStatus.DRY_RUN_READY,
            base_url=normalized_base_url,
            source_id=source_id,
            source_kind=source_kind,
            device_id=device_id,
            sequence_no=sequence_no,
            observed_at=observed_at,
            payload_sha256=envelope.payload_sha256,
            envelope_id=envelope.envelope_id,
            dedupe_key=envelope.dedupe_key,
            request_body_sha256=request_body_sha256,
            network_send_attempted=False,
            send_performed=False,
        )

    request = RuntimeStreamHttpRequest(
        endpoint_url=f"{normalized_base_url}/runtime/streams/http-push/observations",
        body=body,
        timeout_seconds=timeout_seconds,
    )
    try:
        response = _normalize_response((transport or _urllib_json_post)(request))
    except Exception as exc:
        return _result(
            status=RuntimeStreamSignedSampleStatus.TRANSPORT_ERROR,
            base_url=normalized_base_url,
            source_id=source_id,
            source_kind=source_kind,
            device_id=device_id,
            sequence_no=sequence_no,
            observed_at=observed_at,
            payload_sha256=envelope.payload_sha256,
            envelope_id=envelope.envelope_id,
            dedupe_key=envelope.dedupe_key,
            request_body_sha256=request_body_sha256,
            network_send_attempted=True,
            send_performed=False,
            error_summary=f"{type(exc).__name__}: {exc}",
        )

    response_summary = _safe_response_summary(response.response_body)
    sent = 200 <= response.status_code < 300
    return _result(
        status=(
            RuntimeStreamSignedSampleStatus.SENT
            if sent
            else RuntimeStreamSignedSampleStatus.TRANSPORT_ERROR
        ),
        base_url=normalized_base_url,
        source_id=source_id,
        source_kind=source_kind,
        device_id=device_id,
        sequence_no=sequence_no,
        observed_at=observed_at,
        payload_sha256=envelope.payload_sha256,
        envelope_id=envelope.envelope_id,
        dedupe_key=envelope.dedupe_key,
        request_body_sha256=request_body_sha256,
        network_send_attempted=True,
        send_performed=sent,
        http_status_code=response.status_code,
        response_body_sha256=_response_body_hash(response.response_body),
        response_status=response_summary.get("status"),
        response_admission_status=response_summary.get("admission_status"),
        response_transport_surface=response_summary.get("transport_surface"),
        response_ingest_surface=response_summary.get("ingest_surface"),
        response_admission_transport=response_summary.get("admission_transport"),
        observations_accepted=response_summary.get("observations_accepted"),
        safety_level=response_summary.get("safety_level"),
        blockers=[] if sent else [f"http_status:{response.status_code}"],
    )


def run_runtime_stream_signed_sample_cli(
    argv: Sequence[str] | None = None,
    *,
    transport: Callable[[RuntimeStreamHttpRequest], Any] | None = None,
) -> tuple[int, RuntimeStreamSignedSampleResult]:
    args = _build_parser().parse_args(argv)
    payload = json.loads(Path(args.payload).read_text(encoding="utf-8"))
    secret_key = _read_secret(args.secret, args.secret_file)
    result = run_runtime_stream_signed_sample(
        base_url=args.base_url,
        payload=payload,
        secret_key=secret_key,
        source_id=args.source_id,
        source_kind=args.source_kind,
        device_id=args.device_id,
        sequence_no=args.sequence_no,
        observed_at=args.observed_at,
        received_at=args.received_at,
        send=args.send,
        timeout_seconds=args.timeout_seconds,
        transport=transport,
    )
    _write_or_print(result, Path(args.output) if args.output else None)
    return (0 if result.status in {"dry_run_ready", "sent"} else 2), result


def main(argv: Sequence[str] | None = None) -> int:
    exit_code, _ = run_runtime_stream_signed_sample_cli(argv)
    return exit_code


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build or send a signed HTTP-push runtime observation sample. "
            "Without --send this is a dry-run and performs no network request."
        )
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:9099")
    parser.add_argument("--payload", required=True, help="JSON object payload file.")
    parser.add_argument("--secret", help="Admission secret value.")
    parser.add_argument("--secret-file", help="Admission secret file.")
    parser.add_argument("--source-id", default="runtime_source.apple_watch.v0")
    parser.add_argument("--source-kind", default="apple_watch")
    parser.add_argument("--device-id", default="operator.sample.watch")
    parser.add_argument("--sequence-no", type=int, default=1)
    parser.add_argument("--observed-at", default="2026-05-20T00:00:00+08:00")
    parser.add_argument("--received-at", default="2026-05-20T00:00:00+08:00")
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    parser.add_argument("--send", action="store_true")
    parser.add_argument("--output")
    return parser


def _read_secret(secret: str | None, secret_file: str | None) -> str | None:
    if secret:
        return secret
    if secret_file:
        path = Path(secret_file)
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
    return None


def _urllib_json_post(request: RuntimeStreamHttpRequest) -> RuntimeStreamHttpResponse:
    body = json.dumps(
        request.body,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    http_request = urllib.request.Request(
        request.endpoint_url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(http_request, timeout=request.timeout_seconds) as response:
            return RuntimeStreamHttpResponse(
                status_code=int(response.status),
                response_body=response.read().decode("utf-8", errors="replace"),
            )
    except urllib.error.HTTPError as exc:
        return RuntimeStreamHttpResponse(
            status_code=int(exc.code),
            response_body=exc.read().decode("utf-8", errors="replace"),
        )


def _normalize_response(response: Any) -> RuntimeStreamHttpResponse:
    if isinstance(response, RuntimeStreamHttpResponse):
        return response
    if isinstance(response, dict):
        return RuntimeStreamHttpResponse(
            status_code=int(response.get("status_code", 0)),
            response_body=str(response.get("response_body", "")),
        )
    raise TypeError("transport must return a dict or RuntimeStreamHttpResponse")


def _safe_response_summary(response_body: str) -> dict[str, Any]:
    try:
        parsed = json.loads(response_body) if response_body else {}
    except json.JSONDecodeError:
        parsed = {}
    if not isinstance(parsed, dict):
        return {}
    admission = parsed.get("admission")
    return {
        "status": _string_or_none(parsed.get("status")),
        "admission_status": (
            _string_or_none(admission.get("status"))
            if isinstance(admission, dict)
            else None
        ),
        "transport_surface": _string_or_none(parsed.get("transport_surface")),
        "ingest_surface": _string_or_none(parsed.get("ingest_surface")),
        "admission_transport": _string_or_none(parsed.get("admission_transport")),
        "observations_accepted": (
            parsed.get("observations_accepted")
            if isinstance(parsed.get("observations_accepted"), int)
            else None
        ),
        "safety_level": _string_or_none(parsed.get("safety_level")),
    }


def _result(
    *,
    status: RuntimeStreamSignedSampleStatus,
    base_url: str,
    source_id: str,
    source_kind: str,
    device_id: str,
    sequence_no: int,
    observed_at: str,
    network_send_attempted: bool,
    send_performed: bool,
    payload_sha256: str | None = None,
    envelope_id: str | None = None,
    dedupe_key: str | None = None,
    request_body_sha256: str | None = None,
    http_status_code: int | None = None,
    response_body_sha256: str | None = None,
    response_status: str | None = None,
    response_admission_status: str | None = None,
    response_transport_surface: str | None = None,
    response_ingest_surface: str | None = None,
    response_admission_transport: str | None = None,
    observations_accepted: int | None = None,
    safety_level: str | None = None,
    blockers: list[str] | None = None,
    error_summary: str | None = None,
) -> RuntimeStreamSignedSampleResult:
    active_blockers = blockers or []
    return RuntimeStreamSignedSampleResult(
        status=status,
        base_url=base_url,
        source_id=source_id,
        source_kind=source_kind,
        device_id=device_id,
        sequence_no=sequence_no,
        observed_at=observed_at,
        payload_sha256=payload_sha256,
        envelope_id=envelope_id,
        dedupe_key=dedupe_key,
        request_body_sha256=request_body_sha256,
        network_send_attempted=network_send_attempted,
        send_performed=send_performed,
        http_status_code=http_status_code,
        response_body_sha256=response_body_sha256,
        response_status=response_status,
        response_admission_status=response_admission_status,
        response_transport_surface=response_transport_surface,
        response_ingest_surface=response_ingest_surface,
        response_admission_transport=response_admission_transport,
        observations_accepted=observations_accepted,
        safety_level=safety_level,
        blocker_count=len(active_blockers),
        blocker_reasons=active_blockers,
        error_summary=error_summary,
    )


def _write_or_print(
    result: RuntimeStreamSignedSampleResult,
    output_path: Path | None,
) -> None:
    payload = result.to_json()
    if output_path is None:
        sys.stdout.write(payload)
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(payload, encoding="utf-8")


def _sha256_json(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _response_body_hash(value: str) -> str | None:
    if not value:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _string_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) else None


if __name__ == "__main__":
    raise SystemExit(main())
