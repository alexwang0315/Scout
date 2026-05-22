from __future__ import annotations

import argparse
import json
import sys
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field

from runtime_input_admission import (
    RuntimeInputAdmissionDecision,
    admit_runtime_observation_input,
    empty_runtime_input_admission_state,
)
from runtime_observation_envelope import build_signed_runtime_observation_envelope
from runtime_stream_device_identity import (
    RuntimeStreamDeviceCredentialRef,
    RuntimeStreamDeviceIdentity,
    RuntimeStreamDeviceRegistry,
)
from runtime_stream_policy import build_default_runtime_stream_policy_manifest


SUMMARY_FILENAME = "real-device-policy-drill-summary.json"


class RealDevicePolicyDrillStatus(StrEnum):
    PASSED = "passed"
    BLOCKED = "blocked"
    FAILED = "failed"


class RealDevicePolicyDrillModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RealDevicePolicyDrillBoundary(RealDevicePolicyDrillModel):
    local_policy_drill_only: Literal[True] = True
    raw_payloads_embedded: Literal[False] = False
    secret_values_embedded: Literal[False] = False
    creates_live_endpoint: Literal[False] = False
    network_send_attempted: Literal[False] = False
    calls_safety_api: Literal[False] = False
    forwards_to_runtime: Literal[False] = False
    incident_bridge_enabled: Literal[False] = False
    remote_notification_send_allowed: Literal[False] = False
    hardware_control_allowed: Literal[False] = False
    phase2_writeback_allowed: Literal[False] = False


class RealDevicePolicyDecisionSummary(RealDevicePolicyDrillModel):
    sequence_no: int = Field(ge=0)
    observed_at: str
    status: str
    reason: str
    device_identity_matched: bool
    queue_depth: int = Field(ge=0)
    payload_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    dedupe_key: str
    safety_api_call_count: Literal[0] = 0
    runtime_forward_count: Literal[0] = 0
    phase2_writeback_count: Literal[0] = 0


class RealDevicePolicyDrillResult(RealDevicePolicyDrillModel):
    artifact_kind: Literal["real_device_policy_drill_summary"] = (
        "real_device_policy_drill_summary"
    )
    status: RealDevicePolicyDrillStatus
    source_id: str
    source_kind: str
    device_id: str
    credential_ref: str | None = None
    token_scope: Literal["runtime:observation:write"] = "runtime:observation:write"
    sequence_start: int = Field(ge=0)
    sequence_end: int = Field(ge=0)
    device_identity_matched: bool = False
    admitted_count: int = Field(default=0, ge=0)
    backpressure_count: int = Field(default=0, ge=0)
    disconnected_queue_count: int = Field(default=0, ge=0)
    latest_point_retained_count: int = Field(default=0, ge=0)
    rejected_count: int = Field(default=0, ge=0)
    safety_api_call_count: Literal[0] = 0
    runtime_forward_count: Literal[0] = 0
    phase2_writeback_count: Literal[0] = 0
    raw_payloads_embedded: Literal[False] = False
    secret_values_embedded: Literal[False] = False
    decisions: list[RealDevicePolicyDecisionSummary] = Field(default_factory=list)
    blocker_count: int = Field(default=0, ge=0)
    blocker_reasons: list[str] = Field(default_factory=list)
    evidence_summary_path: str | None = None
    boundary: RealDevicePolicyDrillBoundary = Field(
        default_factory=RealDevicePolicyDrillBoundary
    )

    def to_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True
        ) + "\n"


def run_real_device_policy_drill(
    *,
    payload: dict[str, Any],
    secret_key: str | None,
    evidence_dir: Path | str | None = None,
    source_id: str = "runtime_source.apple_watch.v0",
    source_kind: str = "apple_watch",
    device_id: str = "operator.real_device.watch",
    credential_ref: str = "credential:operator.real_device.watch.runtime-observation",
    hmac_secret_ref: str = "env:SCOUT_RUNTIME_STREAM_REAL_DEVICE_SECRET",
) -> RealDevicePolicyDrillResult:
    blockers = _blockers(payload=payload, secret_key=secret_key)
    if blockers:
        result = _result(
            status=RealDevicePolicyDrillStatus.BLOCKED,
            source_id=source_id,
            source_kind=source_kind,
            device_id=device_id,
            credential_ref=None,
            sequence_start=1,
            decisions=[],
            blockers=blockers,
            evidence_dir=evidence_dir,
        )
        _write_evidence(result)
        return result

    manifest = build_default_runtime_stream_policy_manifest()
    registry = RuntimeStreamDeviceRegistry(
        registry_id="runtime_stream_device_registry.phase46.policy_drill",
        identities=[
            RuntimeStreamDeviceIdentity(
                source_id=source_id,
                source_kind=source_kind,
                device_id=device_id,
                display_name="Phase 4.6 policy drill device",
                credential=RuntimeStreamDeviceCredentialRef(
                    credential_ref=credential_ref,
                    hmac_secret_ref=hmac_secret_ref,
                ),
            )
        ],
    )
    state = empty_runtime_input_admission_state()
    decisions: list[RuntimeInputAdmissionDecision] = []
    scenarios = [
        (1, "2026-05-21T10:00:00.000+08:00", True, 0),
        (2, "2026-05-21T10:00:00.050+08:00", True, 0),
        (3, "2026-05-21T10:00:01.000+08:00", False, 0),
        (4, "2026-05-21T10:00:02.000+08:00", False, manifest.buffering.retry_attempt_limit),
    ]
    for sequence_no, observed_at, connected, retry_attempt in scenarios:
        envelope = build_signed_runtime_observation_envelope(
            payload,
            secret_key=secret_key or "",
            envelope_id=f"runtime_stream_policy_drill.{sequence_no:04d}",
            source_id=source_id,
            source_kind=source_kind,
            transport="http_push",
            device_id=device_id,
            sequence_no=sequence_no,
            observed_at=observed_at,
            received_at=observed_at,
        )
        decision = admit_runtime_observation_input(
            envelope,
            payload,
            secret_key=secret_key or "",
            policy_manifest=manifest,
            state=state,
            device_registry=registry,
            connected=connected,
            retry_attempt=retry_attempt,
        )
        state = decision.state_after
        decisions.append(decision)

    summaries = [_decision_summary(decision) for decision in decisions]
    expected_statuses = [
        "admitted_not_forwarded",
        "queued_backpressure",
        "queued_disconnected",
        "latest_point_retained",
    ]
    status = (
        RealDevicePolicyDrillStatus.PASSED
        if [summary.status for summary in summaries] == expected_statuses
        else RealDevicePolicyDrillStatus.FAILED
    )
    result = _result(
        status=status,
        source_id=source_id,
        source_kind=source_kind,
        device_id=device_id,
        credential_ref=credential_ref,
        sequence_start=1,
        decisions=summaries,
        blockers=[],
        evidence_dir=evidence_dir,
    )
    _write_evidence(result)
    return result


def run_real_device_policy_drill_cli(
    argv: Sequence[str] | None = None,
) -> tuple[int, RealDevicePolicyDrillResult]:
    args = _build_parser().parse_args(argv)
    payload = json.loads(Path(args.payload).read_text(encoding="utf-8"))
    result = run_real_device_policy_drill(
        payload=payload,
        secret_key=_read_secret(args.secret, args.secret_file),
        evidence_dir=Path(args.evidence_dir) if args.evidence_dir else None,
        source_id=args.source_id,
        source_kind=args.source_kind,
        device_id=args.device_id,
        credential_ref=args.credential_ref,
        hmac_secret_ref=args.hmac_secret_ref,
    )
    if args.output:
        _write_json(result, Path(args.output))
    elif args.evidence_dir is None:
        sys.stdout.write(result.to_json())
    return (0 if result.status == RealDevicePolicyDrillStatus.PASSED else 2), result


def main(argv: Sequence[str] | None = None) -> int:
    exit_code, _ = run_real_device_policy_drill_cli(argv)
    return exit_code


def _blockers(*, payload: dict[str, Any], secret_key: str | None) -> list[str]:
    blockers: list[str] = []
    if not secret_key:
        blockers.append("missing_admission_secret")
    if not isinstance(payload, dict):
        blockers.append("payload_must_be_json_object")
    return blockers


def _decision_summary(
    decision: RuntimeInputAdmissionDecision,
) -> RealDevicePolicyDecisionSummary:
    return RealDevicePolicyDecisionSummary(
        sequence_no=decision.sequence_no,
        observed_at=decision.observed_at,
        status=decision.status.value,
        reason=decision.reason,
        device_identity_matched=decision.device_identity_matched,
        queue_depth=decision.queue_depth,
        payload_sha256=decision.payload_sha256,
        dedupe_key=decision.dedupe_key,
    )


def _result(
    *,
    status: RealDevicePolicyDrillStatus,
    source_id: str,
    source_kind: str,
    device_id: str,
    credential_ref: str | None,
    sequence_start: int,
    decisions: list[RealDevicePolicyDecisionSummary],
    blockers: list[str],
    evidence_dir: Path | str | None,
) -> RealDevicePolicyDrillResult:
    statuses = [decision.status for decision in decisions]
    return RealDevicePolicyDrillResult(
        status=status,
        source_id=source_id,
        source_kind=source_kind,
        device_id=device_id,
        credential_ref=credential_ref,
        sequence_start=sequence_start,
        sequence_end=sequence_start + max(len(decisions) - 1, 0),
        device_identity_matched=bool(decisions) and all(
            decision.device_identity_matched for decision in decisions
        ),
        admitted_count=statuses.count("admitted_not_forwarded"),
        backpressure_count=statuses.count("queued_backpressure"),
        disconnected_queue_count=statuses.count("queued_disconnected"),
        latest_point_retained_count=statuses.count("latest_point_retained"),
        rejected_count=sum(1 for item in statuses if item.startswith("rejected_")),
        decisions=decisions,
        blocker_count=len(blockers),
        blocker_reasons=blockers,
        evidence_summary_path=(
            str(Path(evidence_dir) / SUMMARY_FILENAME) if evidence_dir is not None else None
        ),
    )


def _write_evidence(result: RealDevicePolicyDrillResult) -> None:
    if result.evidence_summary_path is None:
        return
    _write_json(result, Path(result.evidence_summary_path))


def _write_json(result: RealDevicePolicyDrillResult, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(result.to_json(), encoding="utf-8")


def _read_secret(secret: str | None, secret_file: str | None) -> str | None:
    if secret:
        return secret
    if secret_file:
        path = Path(secret_file)
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
    return None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run a local real-device stream policy drill for 10Hz backpressure, "
            "offline retry, and latest-point fallback. No network or /safety calls."
        )
    )
    parser.add_argument("--payload", required=True, help="JSON object payload file.")
    parser.add_argument("--secret", help="Admission secret value.")
    parser.add_argument("--secret-file", help="Admission secret file.")
    parser.add_argument("--source-id", default="runtime_source.apple_watch.v0")
    parser.add_argument("--source-kind", default="apple_watch")
    parser.add_argument("--device-id", default="operator.real_device.watch")
    parser.add_argument(
        "--credential-ref",
        default="credential:operator.real_device.watch.runtime-observation",
    )
    parser.add_argument(
        "--hmac-secret-ref",
        default="env:SCOUT_RUNTIME_STREAM_REAL_DEVICE_SECRET",
    )
    parser.add_argument("--evidence-dir")
    parser.add_argument("--output")
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
