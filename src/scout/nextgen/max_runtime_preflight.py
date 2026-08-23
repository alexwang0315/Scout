"""Fail-closed readiness preflight for experimental Modular MAX runtimes."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid4

import httpx
from pydantic import Field, model_validator

from scout.nextgen.openai_compatible_backend import (
    OpenAICompatibleBackendConfig,
    OpenAICompatibleTransportScope,
)
from scout.schemas.base import NonEmptyStr, SchemaModel

MAX_PREFLIGHT_EXPERIMENT_ID = "SCOUT-AI-EXP-MAX-PREFLIGHT-001"
MAX_PREFLIGHT_RESPONSE_BYTES = 1024 * 1024
MAX_PREFLIGHT_SOURCE_REFS = (
    "https://max.modular.com/packages/",
    "https://max.modular.com/rest-api/health/",
    "https://max.modular.com/rest-api/models/",
)
_CHECK_ORDER = (
    "host_compatibility",
    "cli_availability",
    "endpoint_health",
    "model_inventory",
    "provider_identity",
    "authority_boundary",
)
_MIN_MEMORY_BYTES = 8 * 1024**3
_MIN_GLIBC = (2, 34)
_REQUIRED_X86_64_V3_FEATURES = frozenset(
    {"avx", "avx2", "bmi1", "bmi2", "f16c", "fma", "lzcnt", "movbe", "xsave"}
)


class MaxReadinessCheckStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"
    NOT_RUN = "not_run"
    NOT_APPLICABLE = "not_applicable"


class MaxRuntimeReadinessDisposition(StrEnum):
    READY_FOR_BEHAVIOR_QUALIFICATION = "ready_for_behavior_qualification"
    HOST_INCOMPATIBLE = "host_incompatible"
    CLI_UNAVAILABLE = "cli_unavailable"
    ENDPOINT_UNAVAILABLE = "endpoint_unavailable"
    MODEL_MISMATCH = "model_mismatch"
    FAILED = "failed"


class MaxHostFacts(SchemaModel):
    os_family: NonEmptyStr
    machine: NonEmptyStr
    os_version: NonEmptyStr
    python_version: NonEmptyStr
    memory_bytes: int | None = Field(default=None, ge=0)
    glibc_version: str | None = None
    cpu_model: str | None = None
    cpu_features: tuple[NonEmptyStr, ...] = ()

    @model_validator(mode="after")
    def validate_features(self) -> MaxHostFacts:
        if len(self.cpu_features) != len(set(self.cpu_features)):
            raise ValueError("MAX host CPU features must be unique")
        return self


class MaxCliObservation(SchemaModel):
    available: bool
    version: str | None = None
    error_type: str | None = None

    @model_validator(mode="after")
    def validate_cli_observation(self) -> MaxCliObservation:
        if not self.available and self.version is not None:
            raise ValueError("unavailable MAX CLI cannot declare a version")
        return self


class MaxEndpointObservation(SchemaModel):
    health_status_code: int | None = Field(default=None, ge=100, le=599)
    health_path: str | None = None
    model_status_code: int | None = Field(default=None, ge=100, le=599)
    observed_model_ids: tuple[NonEmptyStr, ...] = ()
    error_type: str | None = None

    @model_validator(mode="after")
    def validate_endpoint_observation(self) -> MaxEndpointObservation:
        if len(self.observed_model_ids) != len(set(self.observed_model_ids)):
            raise ValueError("observed MAX model ids must be unique")
        if self.health_path is not None and not self.health_path.startswith("/"):
            raise ValueError("MAX health path must be absolute")
        return self


class MaxRuntimeReadinessCheck(SchemaModel):
    check_id: NonEmptyStr
    status: MaxReadinessCheckStatus
    summary: NonEmptyStr
    latency_ms: int = Field(default=0, ge=0)
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False


class MaxQualificationInputBinding(SchemaModel):
    case_file: NonEmptyStr
    case_sha256: NonEmptyStr
    evidence_catalog_file: NonEmptyStr
    evidence_catalog_sha256: NonEmptyStr
    qualification_module_sha256: NonEmptyStr
    qualification_launcher_sha256: NonEmptyStr
    required_checks: tuple[NonEmptyStr, ...] = (
        "configuration",
        "basic_chat",
        "typed_output",
        "tool_calling",
        "praison_mcp",
        "authority_boundary",
    )


class MaxRuntimeReadinessReport(SchemaModel):
    schema_version: Literal["scout.max_runtime_preflight.v0"] = (
        "scout.max_runtime_preflight.v0"
    )
    experiment_id: Literal["SCOUT-AI-EXP-MAX-PREFLIGHT-001"] = (
        MAX_PREFLIGHT_EXPERIMENT_ID
    )
    preflight_id: UUID = Field(default_factory=uuid4)
    generated_at: datetime
    disposition: MaxRuntimeReadinessDisposition
    runtime_id: NonEmptyStr
    provider: Literal["max"] = "max"
    requested_model_id: NonEmptyStr
    accepted_observed_model_ids: tuple[NonEmptyStr, ...]
    transport_scope: NonEmptyStr
    endpoint_sha256: NonEmptyStr
    runtime_config_sha256: NonEmptyStr
    deployment_mode: Literal["local_process", "external_service"]
    host: MaxHostFacts
    cli: MaxCliObservation
    endpoint: MaxEndpointObservation
    checks: tuple[MaxRuntimeReadinessCheck, ...]
    qualification_inputs: MaxQualificationInputBinding | None = None
    source_refs: tuple[NonEmptyStr, ...] = MAX_PREFLIGHT_SOURCE_REFS
    provider_identity_verified: Literal[False] = False
    provider_identity_basis: Literal["operator_declared"] = "operator_declared"
    model_request_count: Literal[0] = 0
    report_hash: NonEmptyStr
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False

    @model_validator(mode="after")
    def validate_report(self) -> MaxRuntimeReadinessReport:
        if tuple(check.check_id for check in self.checks) != _CHECK_ORDER:
            raise ValueError("MAX preflight checks are missing or out of order")
        return self


def collect_max_host_facts() -> MaxHostFacts:
    os_family = platform.system().lower() or "unknown"
    machine = platform.machine().lower() or "unknown"
    os_version = _os_version(os_family)
    glibc_version = platform.libc_ver()[1] if os_family == "linux" else None
    cpu_model, cpu_features = _linux_cpu_facts() if os_family == "linux" else (None, ())
    return MaxHostFacts(
        os_family=os_family,
        machine=machine,
        os_version=os_version,
        python_version=platform.python_version(),
        memory_bytes=_total_memory_bytes(),
        glibc_version=glibc_version or None,
        cpu_model=cpu_model,
        cpu_features=cpu_features,
    )


def collect_max_cli_observation() -> MaxCliObservation:
    executable = shutil.which("max")
    if executable is None:
        return MaxCliObservation(available=False)
    try:
        result = subprocess.run(
            [executable, "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
            env={"PATH": os.environ.get("PATH", "")},
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return MaxCliObservation(
            available=True,
            error_type=type(exc).__name__,
        )
    version = (result.stdout or result.stderr).strip()[:512] or None
    return MaxCliObservation(
        available=True,
        version=version,
        error_type=None if result.returncode == 0 else "MaxVersionCommandFailed",
    )


def probe_max_endpoint(
    config: OpenAICompatibleBackendConfig,
    *,
    timeout_seconds: float = 2,
    environ: Mapping[str, str] | None = None,
    transport: httpx.BaseTransport | None = None,
) -> MaxEndpointObservation:
    headers = {"accept": "application/json"}
    if config.api_key_env is not None:
        token = (environ if environ is not None else os.environ).get(
            config.api_key_env
        )
        if not token:
            return MaxEndpointObservation(error_type="CredentialUnavailable")
        headers["authorization"] = f"Bearer {token}"

    health_status: int | None = None
    health_path: str | None = None
    last_error: str | None = None
    with httpx.Client(
        timeout=timeout_seconds,
        follow_redirects=False,
        trust_env=False,
        transport=transport,
        headers=headers,
    ) as client:
        for url in _health_urls(config):
            try:
                response = client.get(url)
                health_status = response.status_code
                _require_bounded_response(response)
                payload = response.json()
            except (
                httpx.HTTPError,
                json.JSONDecodeError,
                TypeError,
                ValueError,
            ) as exc:
                last_error = type(exc).__name__
                continue
            if response.status_code == 200 and isinstance(payload, dict):
                if payload.get("status") == "ok":
                    health_path = response.request.url.path
                    break
                last_error = "InvalidHealthPayload"
        if health_path is None:
            return MaxEndpointObservation(
                health_status_code=health_status,
                health_path=None,
                model_status_code=None,
                observed_model_ids=(),
                error_type=last_error or "EndpointHealthUnavailable",
            )

        try:
            model_response = client.get(f"{config.normalized_base_url}/models")
            _require_bounded_response(model_response)
            model_payload = model_response.json()
            model_ids = _parse_model_ids(model_payload)
        except (
            httpx.HTTPError,
            json.JSONDecodeError,
            TypeError,
            ValueError,
        ) as exc:
            return MaxEndpointObservation(
                health_status_code=health_status,
                health_path=health_path,
                model_status_code=None,
                observed_model_ids=(),
                error_type=type(exc).__name__,
            )
    return MaxEndpointObservation(
        health_status_code=health_status,
        health_path=health_path,
        model_status_code=model_response.status_code,
        observed_model_ids=model_ids,
        error_type=None,
    )


def run_max_runtime_preflight(
    *,
    runtime_config_path: Path,
    timeout_seconds: float = 2,
    host_facts: MaxHostFacts | None = None,
    cli_observation: MaxCliObservation | None = None,
    endpoint_observation: MaxEndpointObservation | None = None,
    environ: Mapping[str, str] | None = None,
    case_path: Path | None = None,
    evidence_catalog_path: Path | None = None,
    qualification_launcher_path: Path | None = None,
) -> MaxRuntimeReadinessReport:
    config = OpenAICompatibleBackendConfig.from_json_file(runtime_config_path)
    if config.provider.lower() != "max":
        raise ValueError("MAX runtime preflight requires provider=max")
    host = host_facts or collect_max_host_facts()
    cli = cli_observation or collect_max_cli_observation()
    endpoint_started = time.monotonic()
    endpoint = endpoint_observation or probe_max_endpoint(
        config,
        timeout_seconds=timeout_seconds,
        environ=environ,
    )
    endpoint_latency_ms = int((time.monotonic() - endpoint_started) * 1000)
    local_process = (
        config.transport_scope is OpenAICompatibleTransportScope.LOOPBACK
    )
    checks = _build_checks(
        config=config,
        host=host,
        cli=cli,
        endpoint=endpoint,
        local_process=local_process,
        endpoint_latency_ms=endpoint_latency_ms,
    )
    disposition = _disposition(checks, local_process=local_process)
    qualification_inputs = _qualification_input_binding(
        case_path=case_path,
        evidence_catalog_path=evidence_catalog_path,
        qualification_launcher_path=qualification_launcher_path,
    )
    report = MaxRuntimeReadinessReport(
        generated_at=datetime.now(UTC),
        disposition=disposition,
        runtime_id=config.runtime_id,
        requested_model_id=config.model_id,
        accepted_observed_model_ids=tuple(
            sorted({config.model_id, *config.accepted_observed_model_ids})
        ),
        transport_scope=config.transport_scope.value,
        endpoint_sha256=_text_hash(config.normalized_base_url),
        runtime_config_sha256=_file_hash(runtime_config_path),
        deployment_mode="local_process" if local_process else "external_service",
        host=host,
        cli=cli,
        endpoint=endpoint,
        checks=checks,
        qualification_inputs=qualification_inputs,
        report_hash="pending",
    )
    return report.model_copy(update={"report_hash": max_runtime_readiness_report_hash(report)})


def max_runtime_readiness_report_hash(report: MaxRuntimeReadinessReport) -> str:
    payload = report.model_dump(mode="json")
    payload.pop("report_hash", None)
    return _canonical_hash(payload)


def _build_checks(
    *,
    config: OpenAICompatibleBackendConfig,
    host: MaxHostFacts,
    cli: MaxCliObservation,
    endpoint: MaxEndpointObservation,
    local_process: bool,
    endpoint_latency_ms: int,
) -> tuple[MaxRuntimeReadinessCheck, ...]:
    if local_process:
        host_compatible, host_summary = _host_compatibility(host)
        host_check = _check(
            "host_compatibility",
            MaxReadinessCheckStatus.PASSED if host_compatible else MaxReadinessCheckStatus.FAILED,
            host_summary,
        )
        cli_check = _check(
            "cli_availability",
            MaxReadinessCheckStatus.PASSED if cli.available else MaxReadinessCheckStatus.UNAVAILABLE,
            "MAX CLI is available for a managed local launch."
            if cli.available
            else "MAX CLI is not installed on the local host.",
        )
    else:
        host_check = _check(
            "host_compatibility",
            MaxReadinessCheckStatus.NOT_APPLICABLE,
            "The client host does not constrain an external MAX service.",
        )
        cli_check = _check(
            "cli_availability",
            MaxReadinessCheckStatus.NOT_APPLICABLE,
            "An external MAX service does not require a client-side MAX CLI.",
        )

    health_passed = endpoint.health_status_code == 200 and endpoint.health_path is not None
    health_check = _check(
        "endpoint_health",
        MaxReadinessCheckStatus.PASSED
        if health_passed
        else MaxReadinessCheckStatus.UNAVAILABLE,
        "The endpoint returned the bounded MAX health contract."
        if health_passed
        else "No bounded healthy MAX endpoint was observed.",
        latency_ms=endpoint_latency_ms,
    )
    accepted_ids = {config.model_id, *config.accepted_observed_model_ids}
    if not health_passed:
        model_check = _check(
            "model_inventory",
            MaxReadinessCheckStatus.NOT_RUN,
            "Model inventory was not trusted because endpoint health did not pass.",
        )
    elif endpoint.model_status_code != 200:
        model_check = _check(
            "model_inventory",
            MaxReadinessCheckStatus.UNAVAILABLE,
            "The endpoint model inventory was unavailable.",
        )
    elif not accepted_ids.intersection(endpoint.observed_model_ids):
        model_check = _check(
            "model_inventory",
            MaxReadinessCheckStatus.FAILED,
            "The endpoint did not expose an accepted model identity.",
        )
    else:
        model_check = _check(
            "model_inventory",
            MaxReadinessCheckStatus.PASSED,
            "The endpoint exposed an accepted model identity.",
        )
    provider_check = _check(
        "provider_identity",
        MaxReadinessCheckStatus.NOT_APPLICABLE,
        "Behavioral endpoint probing cannot attest that the server implementation is MAX.",
    )
    authority_check = _check(
        "authority_boundary",
        MaxReadinessCheckStatus.PASSED,
        "The runtime remains experimental, candidate-only, and outside safety authority.",
    )
    return (
        host_check,
        cli_check,
        health_check,
        model_check,
        provider_check,
        authority_check,
    )


def _qualification_input_binding(
    *,
    case_path: Path | None,
    evidence_catalog_path: Path | None,
    qualification_launcher_path: Path | None,
) -> MaxQualificationInputBinding | None:
    supplied = (
        case_path is not None,
        evidence_catalog_path is not None,
        qualification_launcher_path is not None,
    )
    if not any(supplied):
        return None
    if not all(supplied):
        raise ValueError(
            "MAX qualification input binding requires case, evidence, and launcher"
        )
    assert case_path is not None
    assert evidence_catalog_path is not None
    assert qualification_launcher_path is not None
    qualification_module_path = Path(__file__).with_name("model_qualification.py")
    return MaxQualificationInputBinding(
        case_file=case_path.name,
        case_sha256=_file_hash(case_path),
        evidence_catalog_file=evidence_catalog_path.name,
        evidence_catalog_sha256=_file_hash(evidence_catalog_path),
        qualification_module_sha256=_file_hash(qualification_module_path),
        qualification_launcher_sha256=_file_hash(qualification_launcher_path),
    )


def _disposition(
    checks: tuple[MaxRuntimeReadinessCheck, ...],
    *,
    local_process: bool,
) -> MaxRuntimeReadinessDisposition:
    by_id = {check.check_id: check for check in checks}
    if (
        by_id["endpoint_health"].status is MaxReadinessCheckStatus.PASSED
        and by_id["model_inventory"].status is MaxReadinessCheckStatus.PASSED
        and by_id["authority_boundary"].status is MaxReadinessCheckStatus.PASSED
    ):
        return MaxRuntimeReadinessDisposition.READY_FOR_BEHAVIOR_QUALIFICATION
    if by_id["model_inventory"].status is MaxReadinessCheckStatus.FAILED:
        return MaxRuntimeReadinessDisposition.MODEL_MISMATCH
    if local_process and by_id["host_compatibility"].status is MaxReadinessCheckStatus.FAILED:
        return MaxRuntimeReadinessDisposition.HOST_INCOMPATIBLE
    if local_process and by_id["cli_availability"].status is MaxReadinessCheckStatus.UNAVAILABLE:
        return MaxRuntimeReadinessDisposition.CLI_UNAVAILABLE
    if by_id["endpoint_health"].status is not MaxReadinessCheckStatus.PASSED:
        return MaxRuntimeReadinessDisposition.ENDPOINT_UNAVAILABLE
    return MaxRuntimeReadinessDisposition.FAILED


def _host_compatibility(host: MaxHostFacts) -> tuple[bool, str]:
    issues: list[str] = []
    python_version = _version_tuple(host.python_version)
    if python_version is None or not ((3, 10) <= python_version[:2] <= (3, 14)):
        issues.append("Python must be 3.10 through 3.14")
    if host.memory_bytes is None or host.memory_bytes < _MIN_MEMORY_BYTES:
        issues.append("at least 8 GiB memory must be observable")

    machine = host.machine.lower()
    if host.os_family.lower() == "darwin":
        if machine not in {"arm64", "aarch64"}:
            issues.append("current MAX macOS packages require Apple silicon")
        os_version = _version_tuple(host.os_version)
        if os_version is None or os_version[0] < 15:
            issues.append("current MAX macOS packages require macOS 15 or later")
    elif host.os_family.lower() == "linux":
        glibc = _version_tuple(host.glibc_version or "")
        if glibc is None or glibc[:2] < _MIN_GLIBC:
            issues.append("MAX Linux packages require glibc 2.34 or later")
        if machine in {"x86_64", "amd64"}:
            missing = _REQUIRED_X86_64_V3_FEATURES.difference(host.cpu_features)
            if missing:
                issues.append("x86-64-v3 CPU features are incomplete")
        elif machine in {"arm64", "aarch64"}:
            if not host.cpu_model or "neoverse" not in host.cpu_model.lower():
                issues.append("ARM64 requires verified Neoverse N1 or newer")
        else:
            issues.append("unsupported Linux machine architecture")
    else:
        issues.append("MAX local serving is not qualified on this operating system")

    if issues:
        return False, "; ".join(issues) + "."
    return True, "The host meets the bounded MAX package compatibility preflight."


def _health_urls(config: OpenAICompatibleBackendConfig) -> tuple[str, ...]:
    parsed = urlsplit(config.normalized_base_url)
    origin_health = urlunsplit((parsed.scheme, parsed.netloc, "/health", "", ""))
    versioned_health = f"{config.normalized_base_url}/health"
    return tuple(dict.fromkeys((origin_health, versioned_health)))


def _parse_model_ids(payload: object) -> tuple[str, ...]:
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise TypeError("invalid MAX model inventory payload")
    model_ids: list[str] = []
    for item in payload["data"]:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise TypeError("invalid MAX model inventory item")
        model_id = item["id"].strip()
        if not model_id:
            raise ValueError("empty MAX model identity")
        model_ids.append(model_id)
    return tuple(sorted(set(model_ids)))


def _require_bounded_response(response: httpx.Response) -> None:
    if len(response.content) > MAX_PREFLIGHT_RESPONSE_BYTES:
        raise ValueError("MAX preflight response exceeded the size limit")


def _check(
    check_id: str,
    status: MaxReadinessCheckStatus,
    summary: str,
    *,
    latency_ms: int = 0,
) -> MaxRuntimeReadinessCheck:
    return MaxRuntimeReadinessCheck(
        check_id=check_id,
        status=status,
        summary=summary,
        latency_ms=latency_ms,
    )


def _os_version(os_family: str) -> str:
    if os_family == "darwin":
        return platform.mac_ver()[0] or platform.release()
    return platform.release() or "unknown"


def _total_memory_bytes() -> int | None:
    try:
        return int(os.sysconf("SC_PAGE_SIZE")) * int(os.sysconf("SC_PHYS_PAGES"))
    except (AttributeError, OSError, TypeError, ValueError):
        return None


def _linux_cpu_facts() -> tuple[str | None, tuple[str, ...]]:
    path = Path("/proc/cpuinfo")
    try:
        text = path.read_text(encoding="utf-8", errors="replace")[:1024 * 1024]
    except OSError:
        return None, ()
    model: str | None = None
    features: set[str] = set()
    for line in text.splitlines():
        key, separator, value = line.partition(":")
        if not separator:
            continue
        normalized_key = key.strip().lower()
        normalized_value = value.strip()
        if model is None and normalized_key in {"model name", "processor"}:
            model = normalized_value[:512] or None
        if normalized_key in {"flags", "features"}:
            features.update(normalized_value.lower().split())
    return model, tuple(sorted(features))


def _version_tuple(value: str) -> tuple[int, ...] | None:
    parts = value.split(".")
    numbers: list[int] = []
    for part in parts:
        digits = "".join(character for character in part if character.isdigit())
        if not digits:
            break
        numbers.append(int(digits))
    return tuple(numbers) if numbers else None


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _text_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_hash(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "MaxCliObservation",
    "MaxEndpointObservation",
    "MaxHostFacts",
    "MaxQualificationInputBinding",
    "MaxReadinessCheckStatus",
    "MaxRuntimeReadinessDisposition",
    "MaxRuntimeReadinessReport",
    "collect_max_cli_observation",
    "collect_max_host_facts",
    "max_runtime_readiness_report_hash",
    "probe_max_endpoint",
    "run_max_runtime_preflight",
]
