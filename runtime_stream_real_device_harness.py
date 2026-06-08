from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any, Callable, Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field

from runtime_stream_signed_sample_client import (
    RuntimeStreamHttpRequest,
    run_runtime_stream_signed_sample,
)


SUMMARY_FILENAME = "real-device-continuous-stream-summary.json"


class RealDeviceStreamHarnessStatus(StrEnum):
    DRY_RUN_READY = "dry_run_ready"
    SENT = "sent"
    BLOCKED = "blocked"
    TRANSPORT_ERROR = "transport_error"


class RealDeviceStreamHarnessModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RealDeviceStreamHarnessBoundary(RealDeviceStreamHarnessModel):
    real_device_harness: Literal[True] = True
    explicit_send_required: Literal[True] = True
    explicit_operator_send_approval_required: Literal[True] = True
    raw_payloads_embedded: Literal[False] = False
    secret_values_embedded: Literal[False] = False
    endpoint_secret_embedded: Literal[False] = False
    remote_notification_send_allowed: Literal[False] = False
    incident_bridge_enable_allowed: Literal[False] = False
    hardware_control_allowed: Literal[False] = False
    phase2_writeback_allowed: Literal[False] = False


class RealDeviceStreamSampleSummary(RealDeviceStreamHarnessModel):
    sequence_no: int = Field(ge=0)
    observed_at: str
    status: str
    payload_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    envelope_id: str | None = None
    dedupe_key: str | None = None
    request_body_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    http_status_code: int | None = None
    response_status: str | None = None
    response_admission_status: str | None = None
    response_transport_surface: str | None = None
    response_ingest_surface: str | None = None
    observations_accepted: int | None = Field(default=None, ge=0)
    safety_level: str | None = None
    blocker_reasons: list[str] = Field(default_factory=list)


class RealDeviceStreamHarnessResult(RealDeviceStreamHarnessModel):
    artifact_kind: Literal["real_device_continuous_stream_harness_result"] = (
        "real_device_continuous_stream_harness_result"
    )
    status: RealDeviceStreamHarnessStatus
    base_url: str
    endpoint_path: Literal["/runtime/streams/http-push/observations"] = (
        "/runtime/streams/http-push/observations"
    )
    source_id: str
    source_kind: str
    device_id: str
    sequence_start: int = Field(ge=0)
    sequence_end: int = Field(ge=0)
    payload_count: int = Field(ge=0)
    sent_count: int = Field(default=0, ge=0)
    dry_run_count: int = Field(default=0, ge=0)
    transport_error_count: int = Field(default=0, ge=0)
    blocked_count: int = Field(default=0, ge=0)
    interval_ms: int = Field(ge=100)
    max_hz: float = Field(default=10.0, gt=0)
    replay_timing_source: str | None = None
    replay_speed_multiplier: float | None = Field(default=None, gt=0)
    send_delay_count: int = Field(default=0, ge=0)
    total_send_delay_ms: int = Field(default=0, ge=0)
    send_delays_ms: list[int] = Field(default_factory=list)
    network_send_attempted: bool
    send_performed: bool
    explicit_send_requested: bool
    explicit_operator_send_approval: bool
    payload_sha256s: list[str] = Field(default_factory=list)
    request_body_sha256s: list[str] = Field(default_factory=list)
    envelope_ids: list[str] = Field(default_factory=list)
    dedupe_keys: list[str] = Field(default_factory=list)
    sample_summaries: list[RealDeviceStreamSampleSummary] = Field(default_factory=list)
    blocker_count: int = 0
    blocker_reasons: list[str] = Field(default_factory=list)
    evidence_summary_path: str | None = None
    boundary: RealDeviceStreamHarnessBoundary = Field(
        default_factory=RealDeviceStreamHarnessBoundary
    )

    def to_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True
        ) + "\n"


def run_real_device_stream_harness(
    *,
    base_url: str,
    payloads: list[dict[str, Any]],
    secret_key: str | None,
    source_id: str = "runtime_source.apple_watch.v0",
    source_kind: str = "apple_watch",
    device_id: str = "operator.real_device.watch",
    sequence_start: int = 1,
    observed_at_start: str = "2026-05-21T00:00:00+08:00",
    interval_ms: int = 100,
    evidence_dir: Path | str | None = None,
    send: bool = False,
    operator_approve_live_send: bool = False,
    send_delays_ms: list[int] | None = None,
    replay_timing_source: str | None = None,
    replay_speed_multiplier: float | None = None,
    timeout_seconds: float = 10.0,
    transport: Callable[[RuntimeStreamHttpRequest], Any] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> RealDeviceStreamHarnessResult:
    normalized_base_url = base_url.rstrip("/")
    blockers = _blockers(
        payloads=payloads,
        secret_key=secret_key,
        interval_ms=interval_ms,
        send=send,
        operator_approve_live_send=operator_approve_live_send,
    )
    if blockers:
        result = _result(
            status=RealDeviceStreamHarnessStatus.BLOCKED,
            base_url=normalized_base_url,
            source_id=source_id,
            source_kind=source_kind,
            device_id=device_id,
            sequence_start=sequence_start,
            payload_count=len(payloads) if isinstance(payloads, list) else 0,
            interval_ms=max(interval_ms, 100),
            send=send,
            operator_approve_live_send=operator_approve_live_send,
            network_send_attempted=False,
            send_performed=False,
            sample_summaries=[],
            blockers=blockers,
            evidence_dir=evidence_dir,
            send_delays_ms=send_delays_ms,
            replay_timing_source=replay_timing_source,
            replay_speed_multiplier=replay_speed_multiplier,
        )
        _write_evidence(result)
        return result

    normalized_send_delays_ms = _normalize_send_delays_ms(
        send_delays_ms,
        payload_count=len(payloads),
    )
    sample_summaries: list[RealDeviceStreamSampleSummary] = []
    for offset, payload in enumerate(payloads):
        if send and offset > 0:
            delay_ms = _delay_for_offset(normalized_send_delays_ms, offset)
            if delay_ms > 0:
                sleep(delay_ms / 1000.0)
        sequence_no = sequence_start + offset
        observed_at = _observed_at(observed_at_start, interval_ms=interval_ms, offset=offset)
        sample = run_runtime_stream_signed_sample(
            base_url=normalized_base_url,
            payload=payload,
            secret_key=secret_key,
            source_id=source_id,
            source_kind=source_kind,
            device_id=device_id,
            sequence_no=sequence_no,
            observed_at=observed_at,
            received_at=observed_at,
            device=source_kind,
            source="real_device_continuous_stream_harness",
            send=send,
            timeout_seconds=timeout_seconds,
            transport=transport,
        )
        sample_summaries.append(
            RealDeviceStreamSampleSummary(
                sequence_no=sequence_no,
                observed_at=observed_at,
                status=str(sample.status),
                payload_sha256=sample.payload_sha256,
                envelope_id=sample.envelope_id,
                dedupe_key=sample.dedupe_key,
                request_body_sha256=sample.request_body_sha256,
                http_status_code=sample.http_status_code,
                response_status=sample.response_status,
                response_admission_status=sample.response_admission_status,
                response_transport_surface=sample.response_transport_surface,
                response_ingest_surface=sample.response_ingest_surface,
                observations_accepted=sample.observations_accepted,
                safety_level=sample.safety_level,
                blocker_reasons=list(sample.blocker_reasons),
            )
        )

    status = _aggregate_status(sample_summaries, send=send)
    result = _result(
        status=status,
        base_url=normalized_base_url,
        source_id=source_id,
        source_kind=source_kind,
        device_id=device_id,
        sequence_start=sequence_start,
        payload_count=len(payloads),
        interval_ms=interval_ms,
        send=send,
        operator_approve_live_send=operator_approve_live_send,
        network_send_attempted=send,
        send_performed=status == RealDeviceStreamHarnessStatus.SENT,
        sample_summaries=sample_summaries,
        blockers=[],
        evidence_dir=evidence_dir,
        send_delays_ms=normalized_send_delays_ms,
        replay_timing_source=replay_timing_source,
        replay_speed_multiplier=replay_speed_multiplier,
    )
    _write_evidence(result)
    return result


def run_real_device_stream_harness_cli(
    argv: Sequence[str] | None = None,
    *,
    transport: Callable[[RuntimeStreamHttpRequest], Any] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[int, RealDeviceStreamHarnessResult]:
    args = _build_parser().parse_args(argv)
    payloads, replay_timing = _read_payload_batch(Path(args.payloads))
    secret_key = _read_secret(args.secret, args.secret_file)
    result = run_real_device_stream_harness(
        base_url=args.base_url,
        payloads=payloads,
        secret_key=secret_key,
        source_id=args.source_id,
        source_kind=args.source_kind,
        device_id=args.device_id,
        sequence_start=args.sequence_start,
        observed_at_start=args.observed_at_start,
        interval_ms=args.interval_ms,
        evidence_dir=Path(args.evidence_dir) if args.evidence_dir else None,
        send=args.send,
        operator_approve_live_send=args.operator_approve_live_send,
        send_delays_ms=(
            replay_timing.get("send_delays_ms")
            if isinstance(replay_timing.get("send_delays_ms"), list)
            else None
        ),
        replay_timing_source=(
            replay_timing.get("timing_source")
            if isinstance(replay_timing.get("timing_source"), str)
            else None
        ),
        replay_speed_multiplier=(
            replay_timing.get("replay_speed_multiplier")
            if isinstance(replay_timing.get("replay_speed_multiplier"), (int, float))
            else None
        ),
        timeout_seconds=args.timeout_seconds,
        transport=transport,
        sleep=sleep,
    )
    if args.output:
        _write_json(result, Path(args.output))
    elif args.evidence_dir is None:
        sys.stdout.write(result.to_json())
    return (0 if result.status in {"dry_run_ready", "sent"} else 2), result


def main(argv: Sequence[str] | None = None) -> int:
    exit_code, _ = run_real_device_stream_harness_cli(argv)
    return exit_code


def _blockers(
    *,
    payloads: list[dict[str, Any]],
    secret_key: str | None,
    interval_ms: int,
    send: bool,
    operator_approve_live_send: bool,
) -> list[str]:
    blockers: list[str] = []
    if not secret_key:
        blockers.append("missing_admission_secret")
    if not isinstance(payloads, list) or not payloads:
        blockers.append("payloads_must_be_non_empty_json_array")
    elif any(not isinstance(payload, dict) for payload in payloads):
        blockers.append("each_payload_must_be_json_object")
    if interval_ms < 100:
        blockers.append("interval_ms_below_10hz_policy")
    if send and not operator_approve_live_send:
        blockers.append("missing_explicit_operator_live_send_approval")
    return blockers


def _result(
    *,
    status: RealDeviceStreamHarnessStatus,
    base_url: str,
    source_id: str,
    source_kind: str,
    device_id: str,
    sequence_start: int,
    payload_count: int,
    interval_ms: int,
    send: bool,
    operator_approve_live_send: bool,
    network_send_attempted: bool,
    send_performed: bool,
    sample_summaries: list[RealDeviceStreamSampleSummary],
    blockers: list[str],
    evidence_dir: Path | str | None,
    send_delays_ms: list[int] | None,
    replay_timing_source: str | None,
    replay_speed_multiplier: float | None,
) -> RealDeviceStreamHarnessResult:
    payload_sha256s = [
        summary.payload_sha256 for summary in sample_summaries if summary.payload_sha256
    ]
    request_body_sha256s = [
        summary.request_body_sha256
        for summary in sample_summaries
        if summary.request_body_sha256
    ]
    envelope_ids = [summary.envelope_id for summary in sample_summaries if summary.envelope_id]
    dedupe_keys = [summary.dedupe_key for summary in sample_summaries if summary.dedupe_key]
    evidence_summary_path = (
        str(Path(evidence_dir) / SUMMARY_FILENAME) if evidence_dir is not None else None
    )
    return RealDeviceStreamHarnessResult(
        status=status,
        base_url=base_url,
        source_id=source_id,
        source_kind=source_kind,
        device_id=device_id,
        sequence_start=sequence_start,
        sequence_end=sequence_start + max(payload_count - 1, 0),
        payload_count=payload_count,
        sent_count=sum(1 for summary in sample_summaries if summary.status == "sent"),
        dry_run_count=sum(
            1 for summary in sample_summaries if summary.status == "dry_run_ready"
        ),
        transport_error_count=sum(
            1 for summary in sample_summaries if summary.status == "transport_error"
        ),
        blocked_count=sum(1 for summary in sample_summaries if summary.status == "sample_blocked"),
        interval_ms=interval_ms,
        replay_timing_source=replay_timing_source,
        replay_speed_multiplier=replay_speed_multiplier,
        send_delay_count=len(send_delays_ms or []),
        total_send_delay_ms=sum(send_delays_ms or []),
        send_delays_ms=list(send_delays_ms or []),
        network_send_attempted=network_send_attempted,
        send_performed=send_performed,
        explicit_send_requested=send,
        explicit_operator_send_approval=operator_approve_live_send,
        payload_sha256s=payload_sha256s,
        request_body_sha256s=request_body_sha256s,
        envelope_ids=envelope_ids,
        dedupe_keys=dedupe_keys,
        sample_summaries=sample_summaries,
        blocker_count=len(blockers),
        blocker_reasons=blockers,
        evidence_summary_path=evidence_summary_path,
    )


def _aggregate_status(
    sample_summaries: list[RealDeviceStreamSampleSummary],
    *,
    send: bool,
) -> RealDeviceStreamHarnessStatus:
    if any(summary.status == "transport_error" for summary in sample_summaries):
        return RealDeviceStreamHarnessStatus.TRANSPORT_ERROR
    if any(summary.status == "sample_blocked" for summary in sample_summaries):
        return RealDeviceStreamHarnessStatus.BLOCKED
    return (
        RealDeviceStreamHarnessStatus.SENT
        if send
        else RealDeviceStreamHarnessStatus.DRY_RUN_READY
    )


def _write_evidence(result: RealDeviceStreamHarnessResult) -> None:
    if result.evidence_summary_path is None:
        return
    _write_json(result, Path(result.evidence_summary_path))


def _write_json(result: RealDeviceStreamHarnessResult, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(result.to_json(), encoding="utf-8")


def _read_payload_batch(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    parsed = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(parsed, dict) and isinstance(parsed.get("payloads"), list):
        timing = parsed.get("replay_timing")
        return parsed["payloads"], timing if isinstance(timing, dict) else {}
    return parsed, {}


def _delay_for_offset(send_delays_ms: list[int] | None, offset: int) -> int:
    if not send_delays_ms or offset >= len(send_delays_ms):
        return 0
    value = send_delays_ms[offset]
    return value if isinstance(value, int) and value > 0 else 0


def _normalize_send_delays_ms(
    send_delays_ms: list[int] | None,
    *,
    payload_count: int,
) -> list[int] | None:
    if send_delays_ms is None:
        return None
    normalized: list[int] = []
    for offset in range(payload_count):
        if offset == 0:
            normalized.append(0)
            continue
        raw_delay = send_delays_ms[offset] if offset < len(send_delays_ms) else 0
        delay = raw_delay if isinstance(raw_delay, int) and raw_delay > 0 else 100
        normalized.append(max(100, delay))
    return normalized


def _read_secret(secret: str | None, secret_file: str | None) -> str | None:
    if secret:
        return secret
    if secret_file:
        path = Path(secret_file)
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
    return None


def _observed_at(observed_at_start: str, *, interval_ms: int, offset: int) -> str:
    start = _parse_datetime(observed_at_start)
    return (start + timedelta(milliseconds=interval_ms * offset)).isoformat()


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build a summary-only real-device continuous stream dry run. "
            "Network sends require both --send and --operator-approve-live-send."
        )
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:9099")
    parser.add_argument("--payloads", required=True, help="JSON array payload file.")
    parser.add_argument("--secret", help="Admission secret value.")
    parser.add_argument("--secret-file", help="Admission secret file.")
    parser.add_argument("--source-id", default="runtime_source.apple_watch.v0")
    parser.add_argument("--source-kind", default="apple_watch")
    parser.add_argument("--device-id", default="operator.real_device.watch")
    parser.add_argument("--sequence-start", type=int, default=1)
    parser.add_argument("--observed-at-start", default="2026-05-21T00:00:00+08:00")
    parser.add_argument("--interval-ms", type=int, default=100)
    parser.add_argument("--evidence-dir")
    parser.add_argument("--output")
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    parser.add_argument("--send", action="store_true")
    parser.add_argument("--operator-approve-live-send", action="store_true")
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
