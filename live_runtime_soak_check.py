from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Callable, Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field


class LiveRuntimeSoakStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"


class LiveRuntimeSoakModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LiveRuntimeSoakBoundary(LiveRuntimeSoakModel):
    read_only_soak: Literal[True] = True
    http_methods_allowed: list[Literal["GET"]] = Field(default_factory=lambda: ["GET"])
    new_observations_sent: Literal[False] = False
    stream_control_mutation_performed: Literal[False] = False
    remote_provider_send_performed: Literal[False] = False
    hardware_control_performed: Literal[False] = False
    sos_sent: Literal[False] = False
    sms_sent: Literal[False] = False
    satellite_sent: Literal[False] = False
    phase2_writeback_performed: Literal[False] = False
    observed_fact_write_performed: Literal[False] = False
    human_review_mutation_performed: Literal[False] = False
    secret_values_embedded: Literal[False] = False
    raw_payloads_embedded: Literal[False] = False


class LiveRuntimeSoakSample(LiveRuntimeSoakModel):
    sampled_at_index: int = Field(ge=0)
    health_status_code: int | None = None
    health_status: str | None = None
    runtime_profile: str | None = None
    live_runtime_enabled: bool | None = None
    runtime_stream_transport_enabled: bool | None = None
    remote_provider_live_send_enabled: bool | None = None
    hardware_provider_control_enabled: bool | None = None
    assistant_status_code: int | None = None
    assistant_provider: str | None = None
    assistant_read_only: bool | None = None
    assistant_model_interpretation: bool | None = None
    assistant_runtime_profile: str | None = None
    assistant_startup_connection_status: str | None = None
    assistant_active_profile: str | None = None
    assistant_token_values_exposed: bool | None = None
    assistant_local_fallback_enabled: bool | None = None
    stream_status_code: int | None = None
    stream_status: str | None = None
    stream_telemetry_status: str | None = None
    stream_telemetry_totals: dict[str, Any] = Field(default_factory=dict)
    stream_read_only_surface: bool | None = None
    stream_transport_routes_mounted: bool | None = None
    stream_observation_ingest_allowed: bool | None = None
    stream_control_mutation_allowed: bool | None = None
    stream_live_provider_send_allowed: bool | None = None
    stream_safety_mutation_allowed: bool | None = None
    stream_phase2_writeback_allowed: bool | None = None
    stream_raw_payloads_embedded: bool | None = None
    control_status_code: int | None = None
    control_status: str | None = None
    control_record_count: int | None = None
    control_calls_safety_api: bool | None = None
    control_controls_device_hardware: bool | None = None
    control_remote_notifications_enabled: bool | None = None
    control_phase2_writeback_count: int | None = None
    provider_control_status_code: int | None = None
    provider_control_status: str | None = None
    provider_control_policy_id: str | None = None
    provider_control_allowed_actions: list[str] = Field(default_factory=list)
    provider_control_operator_authorization_required: bool | None = None
    provider_control_token_value_exposed: bool | None = None
    provider_control_safety_mutation_allowed: bool | None = None
    provider_control_outbound_send_allowed: bool | None = None
    ok: bool
    blocker_reasons: list[str] = Field(default_factory=list)


class LiveRuntimeSoakResult(LiveRuntimeSoakModel):
    artifact_kind: Literal["scout_live_runtime_soak_check"] = (
        "scout_live_runtime_soak_check"
    )
    status: LiveRuntimeSoakStatus
    base_url: str
    expected_runtime_profile: str
    sample_count: int = Field(ge=0)
    interval_seconds: float = Field(ge=0)
    timeout_seconds: float = Field(gt=0)
    provider_control_checked: bool
    samples_all_ok: bool
    blocker_reasons: list[str] = Field(default_factory=list)
    runtime_profile: str | None = None
    assistant_provider: str | None = None
    assistant_startup_connection_status: str | None = None
    assistant_token_values_exposed: bool | None = None
    stream_control_status: str | None = None
    stream_control_record_count: int | None = None
    stream_telemetry_totals: dict[str, Any] = Field(default_factory=dict)
    provider_control_status: str | None = None
    provider_control_allowed_actions: list[str] = Field(default_factory=list)
    provider_control_token_value_exposed: bool | None = None
    raw_payloads_embedded: Literal[False] = False
    secret_values_embedded: Literal[False] = False
    samples: list[LiveRuntimeSoakSample] = Field(default_factory=list)
    boundary: LiveRuntimeSoakBoundary = Field(default_factory=LiveRuntimeSoakBoundary)

    def to_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True
        ) + "\n"


@dataclass(frozen=True)
class LiveRuntimeSoakHttpRequest:
    endpoint_url: str
    path: str
    method: Literal["GET"]
    headers: dict[str, str]
    timeout_seconds: float


@dataclass(frozen=True)
class LiveRuntimeSoakHttpResponse:
    status_code: int
    response_body: str


READ_ONLY_PATHS = (
    "/health",
    "/assistant/status",
    "/runtime/streams/status-read-only",
    "/runtime/streams/control/status",
    "/providers/control/status",
)


def run_live_runtime_soak_check(
    *,
    base_url: str,
    sample_count: int = 3,
    interval_seconds: float = 5.0,
    timeout_seconds: float = 10.0,
    expected_runtime_profile: str = "pi-field-live",
    provider_control_token: str | None = None,
    require_provider_control: bool = True,
    transport: Callable[[LiveRuntimeSoakHttpRequest], Any] | None = None,
    sleep: Callable[[float], Any] = time.sleep,
) -> LiveRuntimeSoakResult:
    normalized_base_url = base_url.rstrip("/")
    blockers: list[str] = []
    if sample_count < 1:
        blockers.append("sample_count_must_be_positive")
    if interval_seconds < 0:
        blockers.append("interval_seconds_must_be_non_negative")
    if require_provider_control and not provider_control_token:
        blockers.append("missing_provider_control_token")
    if blockers:
        return _result(
            status=LiveRuntimeSoakStatus.FAILED,
            base_url=normalized_base_url,
            expected_runtime_profile=expected_runtime_profile,
            sample_count=max(sample_count, 0),
            interval_seconds=max(interval_seconds, 0),
            timeout_seconds=timeout_seconds,
            provider_control_checked=False,
            samples=[],
            blockers=blockers,
        )

    samples: list[LiveRuntimeSoakSample] = []
    for index in range(sample_count):
        samples.append(
            _collect_sample(
                index=index,
                base_url=normalized_base_url,
                timeout_seconds=timeout_seconds,
                expected_runtime_profile=expected_runtime_profile,
                provider_control_token=provider_control_token,
                require_provider_control=require_provider_control,
                transport=transport,
            )
        )
        if index != sample_count - 1:
            sleep(interval_seconds)

    sample_blockers = [
        f"sample_{sample.sampled_at_index}:{reason}"
        for sample in samples
        for reason in sample.blocker_reasons
    ]
    samples_all_ok = all(sample.ok for sample in samples)
    last = samples[-1] if samples else None
    return _result(
        status=LiveRuntimeSoakStatus.PASSED if samples_all_ok else LiveRuntimeSoakStatus.FAILED,
        base_url=normalized_base_url,
        expected_runtime_profile=expected_runtime_profile,
        sample_count=sample_count,
        interval_seconds=interval_seconds,
        timeout_seconds=timeout_seconds,
        provider_control_checked=bool(provider_control_token),
        samples=samples,
        blockers=sample_blockers,
        runtime_profile=last.runtime_profile if last else None,
        assistant_provider=last.assistant_provider if last else None,
        assistant_startup_connection_status=(
            last.assistant_startup_connection_status if last else None
        ),
        assistant_token_values_exposed=last.assistant_token_values_exposed if last else None,
        stream_control_status=last.control_status if last else None,
        stream_control_record_count=last.control_record_count if last else None,
        stream_telemetry_totals=last.stream_telemetry_totals if last else {},
        provider_control_status=last.provider_control_status if last else None,
        provider_control_allowed_actions=(
            last.provider_control_allowed_actions if last else []
        ),
        provider_control_token_value_exposed=(
            last.provider_control_token_value_exposed if last else None
        ),
    )


def run_live_runtime_soak_check_cli(
    argv: Sequence[str] | None = None,
    *,
    transport: Callable[[LiveRuntimeSoakHttpRequest], Any] | None = None,
    sleep: Callable[[float], Any] = time.sleep,
) -> tuple[int, LiveRuntimeSoakResult]:
    args = _build_parser().parse_args(argv)
    provider_token = _read_token(args.provider_token, args.provider_token_file)
    result = run_live_runtime_soak_check(
        base_url=args.base_url,
        sample_count=args.sample_count,
        interval_seconds=args.interval_seconds,
        timeout_seconds=args.timeout_seconds,
        expected_runtime_profile=args.expected_runtime_profile,
        provider_control_token=provider_token,
        require_provider_control=not args.allow_missing_provider_token,
        transport=transport,
        sleep=sleep,
    )
    _write_or_print(result, Path(args.output) if args.output else None)
    return (0 if result.status == LiveRuntimeSoakStatus.PASSED else 2), result


def main(argv: Sequence[str] | None = None) -> int:
    exit_code, _ = run_live_runtime_soak_check_cli(argv)
    return exit_code


def _collect_sample(
    *,
    index: int,
    base_url: str,
    timeout_seconds: float,
    expected_runtime_profile: str,
    provider_control_token: str | None,
    require_provider_control: bool,
    transport: Callable[[LiveRuntimeSoakHttpRequest], Any] | None,
) -> LiveRuntimeSoakSample:
    health_code, health = _get_json(
        base_url=base_url,
        path="/health",
        timeout_seconds=timeout_seconds,
        transport=transport,
    )
    assistant_code, assistant = _get_json(
        base_url=base_url,
        path="/assistant/status",
        timeout_seconds=timeout_seconds,
        transport=transport,
    )
    stream_code, stream = _get_json(
        base_url=base_url,
        path="/runtime/streams/status-read-only",
        timeout_seconds=timeout_seconds,
        transport=transport,
    )
    control_code, control = _get_json(
        base_url=base_url,
        path="/runtime/streams/control/status",
        timeout_seconds=timeout_seconds,
        transport=transport,
    )
    provider_code: int | None = None
    provider: dict[str, Any] = {}
    if provider_control_token:
        provider_code, provider = _get_json(
            base_url=base_url,
            path="/providers/control/status",
            timeout_seconds=timeout_seconds,
            provider_control_token=provider_control_token,
            transport=transport,
        )

    optional = _dict(health.get("optional_features"))
    stream_boundary = _dict(stream.get("boundary"))
    telemetry = _dict(stream.get("telemetry"))
    control_boundary = _dict(control.get("boundary"))
    sample = LiveRuntimeSoakSample(
        sampled_at_index=index,
        health_status_code=health_code,
        health_status=_str_or_none(health.get("status")),
        runtime_profile=_str_or_none(health.get("runtime_profile")),
        live_runtime_enabled=_bool_or_none(optional.get("live_runtime_enabled")),
        runtime_stream_transport_enabled=_bool_or_none(
            optional.get("runtime_stream_transport_enabled")
        ),
        remote_provider_live_send_enabled=_bool_or_none(
            optional.get("remote_provider_live_send_enabled")
        ),
        hardware_provider_control_enabled=_bool_or_none(
            optional.get("hardware_provider_control_enabled")
        ),
        assistant_status_code=assistant_code,
        assistant_provider=_str_or_none(assistant.get("provider")),
        assistant_read_only=_bool_or_none(assistant.get("read_only")),
        assistant_model_interpretation=_bool_or_none(
            assistant.get("model_interpretation")
        ),
        assistant_runtime_profile=_str_or_none(assistant.get("runtime_profile")),
        assistant_startup_connection_status=_str_or_none(
            assistant.get("startup_connection_status")
        ),
        assistant_active_profile=_str_or_none(assistant.get("active_profile")),
        assistant_token_values_exposed=_bool_or_none(
            assistant.get("token_values_exposed")
        ),
        assistant_local_fallback_enabled=_bool_or_none(
            assistant.get("local_fallback_enabled")
        ),
        stream_status_code=stream_code,
        stream_status=_str_or_none(stream.get("status")),
        stream_telemetry_status=_str_or_none(telemetry.get("status")),
        stream_telemetry_totals=_dict(telemetry.get("totals")),
        stream_read_only_surface=_bool_or_none(stream_boundary.get("read_only_surface")),
        stream_transport_routes_mounted=_bool_or_none(
            stream_boundary.get("transport_routes_mounted")
        ),
        stream_observation_ingest_allowed=_bool_or_none(
            stream_boundary.get("observation_ingest_allowed")
        ),
        stream_control_mutation_allowed=_bool_or_none(
            stream_boundary.get("stream_control_mutation_allowed")
        ),
        stream_live_provider_send_allowed=_bool_or_none(
            stream_boundary.get("live_provider_send_allowed")
        ),
        stream_safety_mutation_allowed=_bool_or_none(
            stream_boundary.get("safety_mutation_allowed")
        ),
        stream_phase2_writeback_allowed=_bool_or_none(
            stream_boundary.get("phase2_writeback_allowed")
        ),
        stream_raw_payloads_embedded=_bool_or_none(
            stream_boundary.get("raw_payloads_embedded")
        ),
        control_status_code=control_code,
        control_status=_str_or_none(control.get("status")),
        control_record_count=_int_or_none(control.get("record_count")),
        control_calls_safety_api=_bool_or_none(control_boundary.get("calls_safety_api")),
        control_controls_device_hardware=_bool_or_none(
            control_boundary.get("controls_device_hardware")
        ),
        control_remote_notifications_enabled=_bool_or_none(
            control_boundary.get("remote_notifications_enabled")
        ),
        control_phase2_writeback_count=_int_or_none(
            control_boundary.get("phase2_writeback_count")
        ),
        provider_control_status_code=provider_code,
        provider_control_status=_str_or_none(provider.get("status")),
        provider_control_policy_id=_str_or_none(provider.get("policy_id")),
        provider_control_allowed_actions=[
            str(item) for item in provider.get("allowed_actions", [])
        ]
        if isinstance(provider.get("allowed_actions"), list)
        else [],
        provider_control_operator_authorization_required=_bool_or_none(
            provider.get("operator_authorization_required")
        ),
        provider_control_token_value_exposed=_bool_or_none(
            provider.get("token_value_exposed")
        ),
        provider_control_safety_mutation_allowed=_bool_or_none(
            provider.get("safety_mutation_allowed")
        ),
        provider_control_outbound_send_allowed=_bool_or_none(
            provider.get("outbound_send_allowed")
        ),
        ok=True,
    )
    blockers = _sample_blockers(
        sample,
        expected_runtime_profile=expected_runtime_profile,
        require_provider_control=require_provider_control,
    )
    return sample.model_copy(update={"ok": not blockers, "blocker_reasons": blockers})


def _sample_blockers(
    sample: LiveRuntimeSoakSample,
    *,
    expected_runtime_profile: str,
    require_provider_control: bool,
) -> list[str]:
    blockers: list[str] = []
    _expect(blockers, sample.health_status_code == 200, "health_status_code")
    _expect(blockers, sample.health_status == "ok", "health_status_not_ok")
    _expect(
        blockers,
        sample.runtime_profile == expected_runtime_profile,
        "runtime_profile_mismatch",
    )
    _expect(blockers, sample.live_runtime_enabled is True, "live_runtime_not_enabled")
    _expect(
        blockers,
        sample.runtime_stream_transport_enabled is True,
        "runtime_stream_transport_not_enabled",
    )
    _expect(blockers, sample.assistant_status_code == 200, "assistant_status_code")
    _expect(blockers, sample.assistant_read_only is True, "assistant_not_read_only")
    _expect(
        blockers,
        sample.assistant_model_interpretation is True,
        "assistant_not_model_interpretation",
    )
    _expect(
        blockers,
        sample.assistant_runtime_profile == expected_runtime_profile,
        "assistant_runtime_profile_mismatch",
    )
    _expect(
        blockers,
        sample.assistant_token_values_exposed is False,
        "assistant_token_values_exposed",
    )
    _expect(blockers, sample.stream_status_code == 200, "stream_status_code")
    _expect(
        blockers,
        sample.stream_read_only_surface is True,
        "stream_not_read_only_surface",
    )
    _expect(
        blockers,
        sample.stream_transport_routes_mounted is True,
        "stream_transport_routes_not_mounted",
    )
    _expect(
        blockers,
        sample.stream_safety_mutation_allowed is False,
        "stream_safety_mutation_allowed",
    )
    _expect(
        blockers,
        sample.stream_phase2_writeback_allowed is False,
        "stream_phase2_writeback_allowed",
    )
    _expect(
        blockers,
        sample.stream_raw_payloads_embedded is False,
        "stream_raw_payloads_embedded",
    )
    _expect(blockers, sample.control_status_code == 200, "control_status_code")
    _expect(blockers, sample.control_status == "observing", "control_not_observing")
    _expect(
        blockers,
        sample.control_calls_safety_api is False,
        "control_calls_safety_api",
    )
    _expect(
        blockers,
        sample.control_controls_device_hardware is False,
        "control_controls_device_hardware",
    )
    _expect(
        blockers,
        sample.control_remote_notifications_enabled is False,
        "control_remote_notifications_enabled",
    )
    _expect(
        blockers,
        sample.control_phase2_writeback_count == 0,
        "control_phase2_writeback_count",
    )
    if require_provider_control:
        _expect(
            blockers,
            sample.provider_control_status_code == 200,
            "provider_control_status_code",
        )
        _expect(
            blockers,
            sample.provider_control_status == "enabled",
            "provider_control_not_enabled",
        )
        _expect(
            blockers,
            sample.provider_control_allowed_actions == ["read_provider_status"],
            "provider_control_actions_not_read_only",
        )
        _expect(
            blockers,
            sample.provider_control_token_value_exposed is False,
            "provider_control_token_value_exposed",
        )
        _expect(
            blockers,
            sample.provider_control_safety_mutation_allowed is False,
            "provider_control_safety_mutation_allowed",
        )
        _expect(
            blockers,
            sample.provider_control_outbound_send_allowed is False,
            "provider_control_outbound_send_allowed",
        )
    return blockers


def _get_json(
    *,
    base_url: str,
    path: str,
    timeout_seconds: float,
    provider_control_token: str | None = None,
    transport: Callable[[LiveRuntimeSoakHttpRequest], Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    headers = {"Accept": "application/json"}
    if provider_control_token:
        headers["Authorization"] = f"Bearer {provider_control_token}"
    request = LiveRuntimeSoakHttpRequest(
        endpoint_url=f"{base_url}{path}",
        path=path,
        method="GET",
        headers=headers,
        timeout_seconds=timeout_seconds,
    )
    try:
        response = _normalize_response((transport or _urllib_json_get)(request))
    except Exception as exc:
        return 0, {"transport_error": f"{type(exc).__name__}: {exc}"}
    return response.status_code, _safe_json_object(response.response_body)


def _urllib_json_get(request: LiveRuntimeSoakHttpRequest) -> LiveRuntimeSoakHttpResponse:
    http_request = urllib.request.Request(
        request.endpoint_url,
        headers=request.headers,
        method="GET",
    )
    try:
        with urllib.request.urlopen(http_request, timeout=request.timeout_seconds) as response:
            return LiveRuntimeSoakHttpResponse(
                status_code=int(response.status),
                response_body=response.read().decode("utf-8", errors="replace"),
            )
    except urllib.error.HTTPError as exc:
        return LiveRuntimeSoakHttpResponse(
            status_code=int(exc.code),
            response_body=exc.read().decode("utf-8", errors="replace"),
        )


def _normalize_response(response: Any) -> LiveRuntimeSoakHttpResponse:
    if isinstance(response, LiveRuntimeSoakHttpResponse):
        return response
    if isinstance(response, dict):
        return LiveRuntimeSoakHttpResponse(
            status_code=int(response.get("status_code", 0)),
            response_body=str(response.get("response_body", "")),
        )
    raise TypeError("transport must return a dict or LiveRuntimeSoakHttpResponse")


def _safe_json_object(response_body: str) -> dict[str, Any]:
    try:
        payload = json.loads(response_body) if response_body else {}
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _result(
    *,
    status: LiveRuntimeSoakStatus,
    base_url: str,
    expected_runtime_profile: str,
    sample_count: int,
    interval_seconds: float,
    timeout_seconds: float,
    provider_control_checked: bool,
    samples: list[LiveRuntimeSoakSample],
    blockers: list[str],
    runtime_profile: str | None = None,
    assistant_provider: str | None = None,
    assistant_startup_connection_status: str | None = None,
    assistant_token_values_exposed: bool | None = None,
    stream_control_status: str | None = None,
    stream_control_record_count: int | None = None,
    stream_telemetry_totals: dict[str, Any] | None = None,
    provider_control_status: str | None = None,
    provider_control_allowed_actions: list[str] | None = None,
    provider_control_token_value_exposed: bool | None = None,
) -> LiveRuntimeSoakResult:
    return LiveRuntimeSoakResult(
        status=status,
        base_url=base_url,
        expected_runtime_profile=expected_runtime_profile,
        sample_count=sample_count,
        interval_seconds=interval_seconds,
        timeout_seconds=timeout_seconds,
        provider_control_checked=provider_control_checked,
        samples_all_ok=status == LiveRuntimeSoakStatus.PASSED,
        blocker_reasons=blockers,
        runtime_profile=runtime_profile,
        assistant_provider=assistant_provider,
        assistant_startup_connection_status=assistant_startup_connection_status,
        assistant_token_values_exposed=assistant_token_values_exposed,
        stream_control_status=stream_control_status,
        stream_control_record_count=stream_control_record_count,
        stream_telemetry_totals=stream_telemetry_totals or {},
        provider_control_status=provider_control_status,
        provider_control_allowed_actions=provider_control_allowed_actions or [],
        provider_control_token_value_exposed=provider_control_token_value_exposed,
        samples=samples,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run a read-only live runtime soak check against health, assistant, "
            "stream status, stream control status, and provider-control status."
        )
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:9099")
    parser.add_argument("--sample-count", type=int, default=3)
    parser.add_argument("--interval-seconds", type=float, default=5.0)
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    parser.add_argument("--expected-runtime-profile", default="pi-field-live")
    parser.add_argument("--provider-token")
    parser.add_argument("--provider-token-file")
    parser.add_argument(
        "--allow-missing-provider-token",
        action="store_true",
        help="Skip provider-control status when no token is available.",
    )
    parser.add_argument("--output")
    return parser


def _read_token(token: str | None, token_file: str | None) -> str | None:
    if token:
        return token
    if token_file:
        path = Path(token_file)
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
    return None


def _write_or_print(result: LiveRuntimeSoakResult, output_path: Path | None) -> None:
    serialized = result.to_json()
    if output_path is None:
        sys.stdout.write(serialized)
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(serialized, encoding="utf-8")


def _expect(blockers: list[str], condition: bool, reason: str) -> None:
    if not condition:
        blockers.append(reason)


def _str_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _bool_or_none(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _int_or_none(value: Any) -> int | None:
    return value if isinstance(value, int) else None


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


if __name__ == "__main__":
    raise SystemExit(main())
