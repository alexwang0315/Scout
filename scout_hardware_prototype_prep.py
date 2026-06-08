from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


DeploymentStage = Literal["pi5_docker_step1"]
EventBusMode = Literal["none", "mqtt", "nats"]
ServiceKind = Literal["runtime", "admin_client", "assistant", "local_model", "event_bus"]
ServiceMode = Literal["manual_start", "disabled", "fixture_only"]

SECRET_MARKERS = (
    "sk-",
    "xoxb-",
    "ghp_",
    "bearer ",
    "api_key=",
    "token=",
    "secret=",
)


class ScoutHardwarePrototypeService(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service_id: str = Field(min_length=1)
    kind: ServiceKind
    mode: ServiceMode
    port: int | None = Field(default=None, ge=1, le=65535)
    endpoint_path: str | None = None


class ScoutHardwarePrototypeTargetProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_.-]+$")
    deployment_stage: DeploymentStage = "pi5_docker_step1"
    host_label: str = Field(min_length=1)
    runtime_base_url: str = Field(min_length=1)
    assistant_base_url: str | None = None
    data_root: str = "/data/scout"
    runtime_profile: str = "pi-field"
    live_hardware_enabled: bool = False
    ai_inference_enabled: bool = False
    event_bus: EventBusMode = "none"
    operator_started_services: bool = False
    assistant_model_config_ref: str | None = None
    expected_services: list[ScoutHardwarePrototypeService] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def reject_secret_like_values(self) -> "ScoutHardwarePrototypeTargetProfile":
        _reject_secret_like(self.model_dump(mode="json"))
        return self


class ScoutHardwarePrototypeBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preflight_only: bool = True
    network_calls_allowed: bool = False
    safety_mutation_calls_allowed: bool = False
    phase1_safety_decision_mutation_allowed: bool = False
    phase2_writeback_allowed: bool = False
    incident_store_mutation_allowed: bool = False
    outbound_messages_allowed: bool = False
    hardware_provider_control_allowed: bool = False
    local_model_start_allowed: bool = False


class ManualSmokeCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    check_id: str
    method: Literal["GET", "POST"]
    url_template: str
    operator_only: bool
    mutation: bool
    notes: str


class ScoutHardwarePrototypePreflightCounts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_service_count: int
    required_manual_check_count: int
    blocker_count: int
    warning_count: int


class ScoutHardwarePrototypePreflightReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: Literal["scout_hardware_prototype_preflight"]
    target_id: str
    status: Literal["ready_for_manual_smoke", "blocked"]
    blockers: list[str]
    warnings: list[str]
    manual_smoke_checks: list[ManualSmokeCheck]
    boundary: ScoutHardwarePrototypeBoundary
    counts: ScoutHardwarePrototypePreflightCounts


def build_scout_hardware_prototype_preflight(
    profile: ScoutHardwarePrototypeTargetProfile,
) -> ScoutHardwarePrototypePreflightReport:
    blockers = _collect_blockers(profile)
    warnings = _collect_warnings(profile)
    manual_checks = _manual_smoke_checks(profile)
    status = "blocked" if blockers else "ready_for_manual_smoke"

    return ScoutHardwarePrototypePreflightReport(
        artifact_kind="scout_hardware_prototype_preflight",
        target_id=profile.target_id,
        status=status,
        blockers=blockers,
        warnings=warnings,
        manual_smoke_checks=manual_checks,
        boundary=ScoutHardwarePrototypeBoundary(),
        counts=ScoutHardwarePrototypePreflightCounts(
            expected_service_count=len(profile.expected_services),
            required_manual_check_count=len(manual_checks),
            blocker_count=len(blockers),
            warning_count=len(warnings),
        ),
    )


def _collect_blockers(profile: ScoutHardwarePrototypeTargetProfile) -> list[str]:
    blockers: list[str] = []
    if profile.deployment_stage != "pi5_docker_step1":
        blockers.append("deployment_stage_must_be_pi5_docker_step1")
    if profile.runtime_profile != "pi-field":
        blockers.append("runtime_profile_must_be_pi_field")
    if profile.data_root != "/data/scout":
        blockers.append("data_root_must_be_data_scout_for_step1")
    if profile.live_hardware_enabled:
        blockers.append("live_hardware_must_stay_disabled_for_step1")
    if profile.ai_inference_enabled:
        blockers.append("ai_inference_must_stay_disabled_for_step1")
    if profile.event_bus != "none":
        blockers.append("event_bus_must_stay_none_for_step1")
    if not _has_enabled_runtime_service(profile.expected_services):
        blockers.append("scout_runtime_manual_service_required")
    if _has_enabled_local_model_service(profile.expected_services):
        blockers.append("local_model_service_must_stay_disabled_for_step1")
    return blockers


def _collect_warnings(profile: ScoutHardwarePrototypeTargetProfile) -> list[str]:
    warnings: list[str] = [
        "offline_preflight_only_no_network_probe_performed",
        "manual_smoke_requires_operator_started_services",
    ]
    if profile.operator_started_services:
        warnings.append("operator_started_services_not_verified_by_preflight")
    return warnings


def _manual_smoke_checks(profile: ScoutHardwarePrototypeTargetProfile) -> list[ManualSmokeCheck]:
    runtime_base = profile.runtime_base_url.rstrip("/")
    return [
        ManualSmokeCheck(
            check_id="runtime_health",
            method="GET",
            url_template=f"{runtime_base}/health",
            operator_only=True,
            mutation=False,
            notes="manual-only health check after an operator starts the Scout runtime",
        ),
        ManualSmokeCheck(
            check_id="runtime_status",
            method="GET",
            url_template=f"{runtime_base}/runtime/status",
            operator_only=True,
            mutation=False,
            notes="manual-only runtime status check; preflight does not open a network connection",
        ),
        ManualSmokeCheck(
            check_id="provider_status",
            method="GET",
            url_template=f"{runtime_base}/providers/status",
            operator_only=True,
            mutation=False,
            notes="manual-only provider projection; providers remain fixture-backed in Step 1",
        ),
        ManualSmokeCheck(
            check_id="fixture_observation_ingest",
            method="POST",
            url_template=f"{runtime_base}/safety/observations",
            operator_only=True,
            mutation=True,
            notes=(
                "manual-only fixture observation smoke; preflight does not execute this request "
                "and it requires an explicit hardware prototype decision"
            ),
        ),
    ]


def _has_enabled_runtime_service(services: list[ScoutHardwarePrototypeService]) -> bool:
    return any(service.kind == "runtime" and service.mode != "disabled" for service in services)


def _has_enabled_local_model_service(services: list[ScoutHardwarePrototypeService]) -> bool:
    return any(service.kind == "local_model" and service.mode != "disabled" for service in services)


def _reject_secret_like(value: object) -> None:
    if isinstance(value, str):
        lowered = value.lower()
        if any(marker in lowered for marker in SECRET_MARKERS):
            raise ValueError("secret-like value is not allowed in hardware prototype target profile")
        return
    if isinstance(value, dict):
        for child in value.values():
            _reject_secret_like(child)
        return
    if isinstance(value, list):
        for child in value:
            _reject_secret_like(child)
