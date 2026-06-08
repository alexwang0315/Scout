from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Callable, Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field


SUMMARY_FILENAME = "real-device-control-drill-summary.json"
PLANNED_ROUTES = [
    "GET /runtime/streams/control/status",
    "POST /runtime/streams/control/pause",
    "POST /runtime/streams/control/resume",
    "GET /runtime/streams/control/status",
]


class RealDeviceControlDrillStatus(StrEnum):
    DRY_RUN_READY = "dry_run_ready"
    PASSED = "passed"
    BLOCKED = "blocked"
    FAILED = "failed"


class RealDeviceControlDrillModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RealDeviceControlDrillBoundary(RealDeviceControlDrillModel):
    operator_control_drill: Literal[True] = True
    explicit_execute_required: Literal[True] = True
    explicit_operator_approval_required: Literal[True] = True
    raw_payloads_embedded: Literal[False] = False
    secret_values_embedded: Literal[False] = False
    controls_device_hardware: Literal[False] = False
    remote_notification_send_allowed: Literal[False] = False
    incident_bridge_enable_allowed: Literal[False] = False
    phase2_writeback_allowed: Literal[False] = False


class RealDeviceControlStepSummary(RealDeviceControlDrillModel):
    method: str
    path: str
    status_code: int | None = None
    response_status: str | None = None
    snapshot_after_status: str | None = None
    token_value_exposed: bool | None = None


class RealDeviceControlDrillResult(RealDeviceControlDrillModel):
    artifact_kind: Literal["real_device_control_drill_summary"] = (
        "real_device_control_drill_summary"
    )
    status: RealDeviceControlDrillStatus
    base_url: str
    planned_route_count: int = Field(ge=0)
    planned_routes: list[str]
    network_request_attempted: bool
    stream_control_mutation_performed: bool
    explicit_execute_requested: bool
    explicit_operator_control_approval: bool
    operator_authorization_required: bool | None = None
    pre_control_status: str | None = None
    pause_status_after: str | None = None
    resume_status_after: str | None = None
    final_control_status: str | None = None
    final_status_restored: bool = False
    steps: list[RealDeviceControlStepSummary] = Field(default_factory=list)
    blocker_count: int = Field(default=0, ge=0)
    blocker_reasons: list[str] = Field(default_factory=list)
    evidence_summary_path: str | None = None
    boundary: RealDeviceControlDrillBoundary = Field(
        default_factory=RealDeviceControlDrillBoundary
    )

    def to_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True
        ) + "\n"


@dataclass(frozen=True)
class RealDeviceControlHttpRequest:
    method: str
    endpoint_url: str
    path: str
    headers: dict[str, str]
    body: dict[str, Any] | None
    timeout_seconds: float


@dataclass(frozen=True)
class RealDeviceControlHttpResponse:
    status_code: int
    response_body: str


def run_real_device_control_drill(
    *,
    base_url: str,
    operator_token: str | None,
    evidence_dir: Path | str | None = None,
    execute: bool = False,
    operator_approve_control_drill: bool = False,
    operator_id: str = "admin.local",
    reason: str = "phase4.6 real-device control drill",
    timeout_seconds: float = 10.0,
    transport: Callable[[RealDeviceControlHttpRequest], Any] | None = None,
) -> RealDeviceControlDrillResult:
    normalized_base_url = base_url.rstrip("/")
    blockers = _blockers(
        operator_token=operator_token,
        execute=execute,
        operator_approve_control_drill=operator_approve_control_drill,
    )
    if blockers:
        result = _result(
            status=RealDeviceControlDrillStatus.BLOCKED,
            base_url=normalized_base_url,
            execute=execute,
            operator_approve_control_drill=operator_approve_control_drill,
            network_request_attempted=False,
            stream_control_mutation_performed=False,
            steps=[],
            blockers=blockers,
            evidence_dir=evidence_dir,
        )
        _write_evidence(result)
        return result

    if not execute:
        result = _result(
            status=RealDeviceControlDrillStatus.DRY_RUN_READY,
            base_url=normalized_base_url,
            execute=False,
            operator_approve_control_drill=operator_approve_control_drill,
            network_request_attempted=False,
            stream_control_mutation_performed=False,
            steps=[],
            blockers=[],
            evidence_dir=evidence_dir,
        )
        _write_evidence(result)
        return result

    requests = _control_requests(
        base_url=normalized_base_url,
        operator_token=operator_token or "",
        operator_id=operator_id,
        reason=reason,
        timeout_seconds=timeout_seconds,
    )
    steps: list[RealDeviceControlStepSummary] = []
    for request in requests:
        response = _normalize_response((transport or _urllib_request)(request))
        steps.append(_step_summary(request, response))

    status = (
        RealDeviceControlDrillStatus.PASSED
        if _all_success(steps) and _final_status(steps) == "observing"
        else RealDeviceControlDrillStatus.FAILED
    )
    result = _result(
        status=status,
        base_url=normalized_base_url,
        execute=True,
        operator_approve_control_drill=operator_approve_control_drill,
        network_request_attempted=True,
        stream_control_mutation_performed=status == RealDeviceControlDrillStatus.PASSED,
        steps=steps,
        blockers=[],
        evidence_dir=evidence_dir,
    )
    _write_evidence(result)
    return result


def run_real_device_control_drill_cli(
    argv: Sequence[str] | None = None,
    *,
    transport: Callable[[RealDeviceControlHttpRequest], Any] | None = None,
) -> tuple[int, RealDeviceControlDrillResult]:
    args = _build_parser().parse_args(argv)
    result = run_real_device_control_drill(
        base_url=args.base_url,
        operator_token=_read_secret(args.operator_token, args.operator_token_file),
        evidence_dir=Path(args.evidence_dir) if args.evidence_dir else None,
        execute=args.execute,
        operator_approve_control_drill=args.operator_approve_control_drill,
        operator_id=args.operator_id,
        reason=args.reason,
        timeout_seconds=args.timeout_seconds,
        transport=transport,
    )
    if args.output:
        _write_json(result, Path(args.output))
    elif args.evidence_dir is None:
        sys.stdout.write(result.to_json())
    return (0 if result.status in {"dry_run_ready", "passed"} else 2), result


def main(argv: Sequence[str] | None = None) -> int:
    exit_code, _ = run_real_device_control_drill_cli(argv)
    return exit_code


def _blockers(
    *,
    operator_token: str | None,
    execute: bool,
    operator_approve_control_drill: bool,
) -> list[str]:
    blockers: list[str] = []
    if execute and not operator_token:
        blockers.append("missing_operator_control_token")
    if execute and not operator_approve_control_drill:
        blockers.append("missing_explicit_operator_control_drill_approval")
    return blockers


def _control_requests(
    *,
    base_url: str,
    operator_token: str,
    operator_id: str,
    reason: str,
    timeout_seconds: float,
) -> list[RealDeviceControlHttpRequest]:
    return [
        _request("GET", "/runtime/streams/control/status", base_url, operator_token, timeout_seconds),
        _request(
            "POST",
            "/runtime/streams/control/pause",
            base_url,
            operator_token,
            timeout_seconds,
            body={"operator_id": operator_id, "reason": reason},
        ),
        _request(
            "POST",
            "/runtime/streams/control/resume",
            base_url,
            operator_token,
            timeout_seconds,
            body={"operator_id": operator_id, "reason": reason},
        ),
        _request("GET", "/runtime/streams/control/status", base_url, operator_token, timeout_seconds),
    ]


def _request(
    method: str,
    path: str,
    base_url: str,
    operator_token: str,
    timeout_seconds: float,
    *,
    body: dict[str, Any] | None = None,
) -> RealDeviceControlHttpRequest:
    return RealDeviceControlHttpRequest(
        method=method,
        endpoint_url=f"{base_url}{path}",
        path=path,
        headers={"Authorization": f"Bearer {operator_token}", "Content-Type": "application/json"},
        body=body,
        timeout_seconds=timeout_seconds,
    )


def _result(
    *,
    status: RealDeviceControlDrillStatus,
    base_url: str,
    execute: bool,
    operator_approve_control_drill: bool,
    network_request_attempted: bool,
    stream_control_mutation_performed: bool,
    steps: list[RealDeviceControlStepSummary],
    blockers: list[str],
    evidence_dir: Path | str | None,
) -> RealDeviceControlDrillResult:
    return RealDeviceControlDrillResult(
        status=status,
        base_url=base_url,
        planned_route_count=len(PLANNED_ROUTES),
        planned_routes=list(PLANNED_ROUTES),
        network_request_attempted=network_request_attempted,
        stream_control_mutation_performed=stream_control_mutation_performed,
        explicit_execute_requested=execute,
        explicit_operator_control_approval=operator_approve_control_drill,
        operator_authorization_required=True if steps else None,
        pre_control_status=steps[0].response_status if len(steps) > 0 else None,
        pause_status_after=steps[1].snapshot_after_status if len(steps) > 1 else None,
        resume_status_after=steps[2].snapshot_after_status if len(steps) > 2 else None,
        final_control_status=_final_status(steps),
        final_status_restored=_final_status(steps) == "observing",
        steps=steps,
        blocker_count=len(blockers),
        blocker_reasons=blockers,
        evidence_summary_path=(
            str(Path(evidence_dir) / SUMMARY_FILENAME) if evidence_dir is not None else None
        ),
    )


def _step_summary(
    request: RealDeviceControlHttpRequest,
    response: RealDeviceControlHttpResponse,
) -> RealDeviceControlStepSummary:
    parsed = _parse_json(response.response_body)
    snapshot_after = parsed.get("snapshot_after")
    return RealDeviceControlStepSummary(
        method=request.method,
        path=request.path,
        status_code=response.status_code,
        response_status=_string_or_none(parsed.get("status")),
        snapshot_after_status=(
            _string_or_none(snapshot_after.get("status"))
            if isinstance(snapshot_after, dict)
            else None
        ),
        token_value_exposed=(
            parsed.get("token_value_exposed")
            if isinstance(parsed.get("token_value_exposed"), bool)
            else None
        ),
    )


def _final_status(steps: list[RealDeviceControlStepSummary]) -> str | None:
    if not steps:
        return None
    return steps[-1].response_status or steps[-1].snapshot_after_status


def _all_success(steps: list[RealDeviceControlStepSummary]) -> bool:
    return bool(steps) and all(
        step.status_code is not None and 200 <= step.status_code < 300
        for step in steps
    )


def _write_evidence(result: RealDeviceControlDrillResult) -> None:
    if result.evidence_summary_path is None:
        return
    _write_json(result, Path(result.evidence_summary_path))


def _write_json(result: RealDeviceControlDrillResult, output_path: Path) -> None:
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


def _urllib_request(request: RealDeviceControlHttpRequest) -> RealDeviceControlHttpResponse:
    body = (
        json.dumps(request.body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        if request.body is not None
        else None
    )
    http_request = urllib.request.Request(
        request.endpoint_url,
        data=body,
        headers=request.headers,
        method=request.method,
    )
    try:
        with urllib.request.urlopen(http_request, timeout=request.timeout_seconds) as response:
            return RealDeviceControlHttpResponse(
                status_code=int(response.status),
                response_body=response.read().decode("utf-8", errors="replace"),
            )
    except urllib.error.HTTPError as exc:
        return RealDeviceControlHttpResponse(
            status_code=int(exc.code),
            response_body=exc.read().decode("utf-8", errors="replace"),
        )


def _normalize_response(response: Any) -> RealDeviceControlHttpResponse:
    if isinstance(response, RealDeviceControlHttpResponse):
        return response
    if isinstance(response, dict):
        return RealDeviceControlHttpResponse(
            status_code=int(response.get("status_code", 0)),
            response_body=str(response.get("response_body", "")),
        )
    raise TypeError("transport must return a dict or RealDeviceControlHttpResponse")


def _parse_json(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value) if value else {}
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _string_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Plan or execute a Phase 4.6 real-device stream pause/resume control drill. "
            "Execution requires --execute and --operator-approve-control-drill."
        )
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:9099")
    parser.add_argument("--operator-token")
    parser.add_argument("--operator-token-file")
    parser.add_argument("--operator-id", default="admin.local")
    parser.add_argument("--reason", default="phase4.6 real-device control drill")
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    parser.add_argument("--evidence-dir")
    parser.add_argument("--output")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--operator-approve-control-drill", action="store_true")
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
