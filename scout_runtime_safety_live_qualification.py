from __future__ import annotations

import argparse
import json
import os
import re
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scout_energy_models import aggregate_sha256
from scout_env import load_scout_env_files
from scout_runtime_safety_gate_adapters import (
    ProductionLiveConnectorHealthExecutionRequest,
    ProductionLiveConnectorHealthExecutorInvocationRequest,
    ProductionLiveProviderExecutionRequest,
    ProductionLiveProviderExecutorEffectBoundaryManifest,
    ProductionLiveProviderExecutorInvocationRequest,
    ProductionLiveProviderRequestContract,
    build_live_observation_from_provider_response_receipt,
    build_live_provider_connector_manifest_from_health_receipt,
    build_provider_response_receipt_from_provider_effect_receipt,
    evaluate_live_connector_health_executor_invocation_guard,
    evaluate_live_provider_executor_effect_boundary_readiness,
    evaluate_live_provider_executor_invocation_guard,
    evaluate_production_live_provider_request_contract,
    execute_live_connector_health_check_with_client,
    execute_live_provider_request_with_client,
)
from scout_weather_integration import (
    CWA_36H_FORECAST,
    fetch_cwa_dataset,
    resolve_cwa_api_key,
)


CwaFetch = Callable[..., dict[str, Any]]
CwaLiveQualificationStatus = Literal[
    "cwa_live_chain_verified",
    "blocked_live_call_not_authorized",
    "blocked_credential_ref_unresolved",
    "blocked_connector_health",
    "blocked_provider_execution",
]

_RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")


class CwaLiveQualificationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_cwa_live_qualification_config"
    artifact_version: str = "scout_cwa_live_qualification_config.v0"
    source_path: str = Field(min_length=1)
    run_id: str = Field(min_length=1, max_length=128)
    execution_host_ref: str = Field(min_length=1)
    route_scope_ref: str = Field(min_length=1)
    route_id: str = Field(min_length=1)
    segment_id: str = Field(min_length=1)
    location_name: str = Field(min_length=1, max_length=64)
    forecast_dataset_id: str = CWA_36H_FORECAST
    connector_id: str = "connector.cwa.weather"
    provider_name: str = "Central Weather Administration"
    source_provider: str = "cwa_weather_fusion_live"
    credential_ref: str = Field(min_length=1)
    operator_identity_ref: str = Field(min_length=1)
    operator_role: str = Field(min_length=1)
    freshness_requirement_minutes: int = Field(default=180, gt=0)
    timeout_seconds: float = Field(default=20.0, gt=0, le=60)
    allow_live_provider_call: bool = False

    @model_validator(mode="after")
    def enforce_config(self) -> "CwaLiveQualificationConfig":
        if not _RUN_ID_PATTERN.fullmatch(self.run_id):
            raise ValueError("run_id must contain only letters, digits, dot, dash, underscore")
        if not self.source_path.startswith("prod://"):
            raise ValueError("source_path must use prod://")
        if not self.execution_host_ref.startswith(("prod://", "pi://")):
            raise ValueError("execution_host_ref must use prod:// or pi://")
        if not self.route_scope_ref.startswith("runtime://"):
            raise ValueError("route_scope_ref must use runtime://")
        if not self.credential_ref.startswith(("secret://", "vault://", "kms://")):
            raise ValueError("credential_ref must be an opaque secret reference")
        if not self.operator_identity_ref.startswith("operator://"):
            raise ValueError("operator_identity_ref must use operator://")
        return self


class CwaLiveQualificationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_cwa_live_qualification_report"
    artifact_version: str = "scout_cwa_live_qualification_report.v0"
    source_path: str
    sha256: str
    status: CwaLiveQualificationStatus
    run_id: str
    execution_host_ref: str
    route_scope_ref: str
    dataset_id: str
    observed_at: datetime
    credential_ref: str
    credential_env_name: str | None = None
    credential_ref_resolved_without_value: bool = False
    connector_health_status: str | None = None
    connector_manifest_status: str | None = None
    provider_request_status: str | None = None
    provider_executor_status: str | None = None
    provider_invocation_status: str | None = None
    provider_execution_status: str | None = None
    provider_effect_intake_status: str | None = None
    provider_response_intake_status: str | None = None
    connector_health_receipt_sha256: str | None = None
    provider_effect_receipt_sha256: str | None = None
    provider_response_receipt_sha256: str | None = None
    connector_health_evidence_ready: bool = False
    live_provider_api_evidence_ready: bool = False
    external_provider_calls_performed: bool = False
    credential_material_used_by_executor: bool = False
    credential_material_embedded: bool = False
    raw_provider_payload_persisted: bool = False
    runtime_ingest_performed: bool = False
    safety_api_called: bool = False
    phase1_l0_l4_state_mutated: bool = False
    outbound_transport_invoked: bool = False
    hardware_control_performed: bool = False
    blockers: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_report(self) -> "CwaLiveQualificationReport":
        if (
            self.credential_material_embedded
            or self.raw_provider_payload_persisted
            or self.runtime_ingest_performed
            or self.safety_api_called
            or self.phase1_l0_l4_state_mutated
            or self.outbound_transport_invoked
            or self.hardware_control_performed
        ):
            raise ValueError("CWA live qualification report cannot contain runtime effects")
        verified = self.status == "cwa_live_chain_verified"
        if verified != (
            self.connector_health_evidence_ready
            and self.live_provider_api_evidence_ready
        ):
            raise ValueError("verified status must match ready CWA evidence")
        if verified and self.blockers:
            raise ValueError("verified CWA report cannot contain blockers")
        return self


def run_cwa_live_qualification(
    config: CwaLiveQualificationConfig | Mapping[str, Any],
    *,
    env: Mapping[str, str],
    fetcher: CwaFetch = fetch_cwa_dataset,
    now: datetime | None = None,
) -> CwaLiveQualificationReport:
    config_model = (
        config
        if isinstance(config, CwaLiveQualificationConfig)
        else CwaLiveQualificationConfig.model_validate(config)
    )
    observed_at = now or datetime.now(timezone.utc)
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("qualification observation time must be timezone-aware")
    report_state: dict[str, Any] = {"observed_at": observed_at}
    if not config_model.allow_live_provider_call:
        return _build_report(
            config_model,
            status="blocked_live_call_not_authorized",
            blockers=["live_provider_call_not_authorized"],
            **report_state,
        )

    try:
        credential_value, credential_env_name = resolve_cwa_api_key(env)
    except RuntimeError:
        return _build_report(
            config_model,
            status="blocked_credential_ref_unresolved",
            blockers=["credential_ref_unresolved"],
            **report_state,
        )
    del credential_value
    report_state.update(
        credential_env_name=credential_env_name,
        credential_ref_resolved_without_value=True,
    )

    operator_sha256 = _ref_sha256(
        config_model,
        "operator-identity",
        config_model.operator_identity_ref,
    )
    health_boundary_ref = (
        f"attestation://connector-health/cwa-weather/{config_model.run_id}/boundary"
    )
    fallback_ref = (
        f"attestation://connector-health/cwa-weather/{config_model.run_id}/fallback"
    )
    source_observation_path = (
        f"provider://cwa/weather/chilai-nanhua/{config_model.run_id}"
    )
    health_invocation = evaluate_live_connector_health_executor_invocation_guard(
        ProductionLiveConnectorHealthExecutorInvocationRequest(
            gate_id="weather_gate",
            connector_id=config_model.connector_id,
            provider_name=config_model.provider_name,
            source_provider=config_model.source_provider,
            source_path=source_observation_path,
            provider_dataset_ids=[config_model.forecast_dataset_id],
            route_scope_ref=config_model.route_scope_ref,
            credential_ref=config_model.credential_ref,
            freshness_requirement_minutes=config_model.freshness_requirement_minutes,
            reviewed_connector_health_effect_boundary_ref=health_boundary_ref,
            reviewed_connector_health_effect_boundary_sha256=_ref_sha256(
                config_model,
                "connector-health-boundary",
                health_boundary_ref,
            ),
            fallback_plan_ref=fallback_ref,
            fallback_plan_sha256=_ref_sha256(
                config_model,
                "connector-health-fallback",
                fallback_ref,
            ),
            operator_identity_ref=config_model.operator_identity_ref,
            operator_identity_sha256=operator_sha256,
            operator_role=config_model.operator_role,
            explicit_confirmation=True,
            confirmation_phrase="INVOKE SCOUT CONNECTOR HEALTH",
            idempotency_key=f"{config_model.run_id}-connector-health",
        )
    )
    call_count = 0

    def health_client(
        request: ProductionLiveConnectorHealthExecutionRequest,
    ) -> dict[str, Any]:
        nonlocal call_count
        call_count += 1
        payload = fetcher(
            config_model.forecast_dataset_id,
            params={"locationName": config_model.location_name},
            env=env,
            timeout_s=config_model.timeout_seconds,
        )
        summary = _safe_cwa_payload_summary(
            payload,
            dataset_id=config_model.forecast_dataset_id,
        )
        healthy = bool(summary["provider_success"] and summary["records_present"])
        health_ref = (
            f"attestation://connector/cwa-weather/{config_model.run_id}/"
            f"{'healthy' if healthy else 'unhealthy'}"
        )
        return {
            "source_provider": config_model.source_provider,
            "source_path": request.source_observation_path,
            "provider_dataset_ids": request.provider_dataset_ids,
            "health_status": "healthy" if healthy else "unhealthy",
            "connector_health_ref": health_ref,
            "connector_health_sha256": aggregate_sha256([summary]),
            "route_scoped_request_supported": True,
            "freshness_attestation_supported": True,
            "effect_boundary_required": True,
            "executor_reported_connector_health_check_performed": True,
            "executor_reported_provider_network_request_performed": True,
            "executor_reported_real_provider_api_called": True,
        }

    health_execution = execute_live_connector_health_check_with_client(
        health_invocation,
        health_client,
        source_path=f"{config_model.source_path}/connector-health-execution",
    )
    report_state.update(
        connector_health_status=health_execution.status,
        connector_health_receipt_sha256=health_execution.health_receipt_sha256,
        external_provider_calls_performed=call_count > 0,
        credential_material_used_by_executor=call_count > 0,
    )
    if health_execution.status != "connector_health_receipt_emitted":
        return _build_report(
            config_model,
            status="blocked_connector_health",
            blockers=list(health_execution.blockers),
            **report_state,
        )

    connector_intake = build_live_provider_connector_manifest_from_health_receipt(
        health_execution.health_receipt or {},
        connector_health_invocation=health_invocation,
        source_path=f"{config_model.source_path}/connector-health-intake",
    )
    report_state["connector_manifest_status"] = connector_intake.status
    if connector_intake.status != "connector_manifest_prepared":
        return _build_report(
            config_model,
            status="blocked_connector_health",
            blockers=list(connector_intake.blockers),
            **report_state,
        )

    connector_manifest = connector_intake.connector_manifest
    if connector_manifest is None:
        return _build_report(
            config_model,
            status="blocked_connector_health",
            blockers=["connector_manifest_missing"],
            **report_state,
        )

    request_contract = ProductionLiveProviderRequestContract(
        gate_id="weather_gate",
        connector_id=config_model.connector_id,
        source_provider=config_model.source_provider,
        source_path=source_observation_path,
        route_scope_ref=config_model.route_scope_ref,
        connector_health_ref=connector_manifest.connector_health_ref,
        connector_health_sha256=connector_manifest.connector_health_sha256,
        credential_ref=config_model.credential_ref,
        idempotency_key=f"{config_model.run_id}-provider-request",
        freshness_requirement_minutes=config_model.freshness_requirement_minutes,
        execution_mode="provider_effect_boundary_request",
        reviewed_provider_effect_boundary_ref=(
            f"attestation://provider-effect/cwa-weather/{config_model.run_id}/reviewed"
        ),
        reviewed_provider_effect_boundary_sha256=_ref_sha256(
            config_model,
            "provider-effect-boundary",
            config_model.run_id,
        ),
    )
    request_readiness = evaluate_production_live_provider_request_contract(
        connector_manifest,
        request_contract,
        source_path=f"{config_model.source_path}/provider-request-readiness",
    )
    report_state["provider_request_status"] = request_readiness.status
    if request_readiness.status != "provider_request_boundary_authorized":
        return _build_report(
            config_model,
            status="blocked_provider_execution",
            blockers=list(request_readiness.blockers),
            **report_state,
        )

    executor_manifest = _build_provider_executor_manifest(
        config_model,
        request_readiness,
    )
    executor_readiness = evaluate_live_provider_executor_effect_boundary_readiness(
        request_readiness,
        executor_manifest,
        source_path=f"{config_model.source_path}/provider-executor-readiness",
    )
    report_state["provider_executor_status"] = executor_readiness.status
    if executor_readiness.status != "ready_for_reviewed_provider_effect_boundary":
        return _build_report(
            config_model,
            status="blocked_provider_execution",
            blockers=list(executor_readiness.blockers),
            **report_state,
        )

    invocation = evaluate_live_provider_executor_invocation_guard(
        executor_readiness,
        _build_provider_invocation_request(
            config_model,
            executor_readiness,
            operator_sha256=operator_sha256,
        ),
        source_path=f"{config_model.source_path}/provider-invocation",
    )
    report_state["provider_invocation_status"] = invocation.status
    if invocation.status != "provider_executor_invocation_authorized":
        return _build_report(
            config_model,
            status="blocked_provider_execution",
            blockers=list(invocation.blockers),
            **report_state,
        )

    def provider_client(request: ProductionLiveProviderExecutionRequest) -> dict[str, Any]:
        nonlocal call_count
        call_count += 1
        payload = fetcher(
            config_model.forecast_dataset_id,
            params={"locationName": config_model.location_name},
            env=env,
            timeout_s=config_model.timeout_seconds,
        )
        summary = _safe_cwa_payload_summary(
            payload,
            dataset_id=config_model.forecast_dataset_id,
        )
        success = bool(summary["provider_success"] and summary["records_present"])
        evidence_ref = (
            f"cwa://opendata/{config_model.forecast_dataset_id}/{config_model.run_id}"
        )
        freshness_ref = (
            f"attestation://freshness/cwa-weather/network-response/"
            f"{config_model.run_id}"
        )
        return {
            "source_provider": config_model.source_provider,
            "source_path": f"{request.source_observation_path}/effect",
            "source_observation_path": request.source_observation_path,
            "provider_dataset_ids": [config_model.forecast_dataset_id],
            "provider_evidence_ref": evidence_ref,
            "provider_evidence_sha256": aggregate_sha256([summary]),
            "current_observation_ref": evidence_ref,
            "freshness_attestation_ref": freshness_ref,
            "freshness_attestation_sha256": _ref_sha256(
                config_model,
                "network-response-freshness",
                freshness_ref,
            ),
            "source_age_minutes": 0,
            "freshness_requirement_minutes": (
                config_model.freshness_requirement_minutes
            ),
            "response_status": "success" if success else "failed",
            "observed_at_offset_s": 0,
            "warning_level": "none",
            "route_context": {
                "route_id": config_model.route_id,
                "segment_id": config_model.segment_id,
            },
            "evidence_refs": [evidence_ref],
            "confidence": "medium",
            "executor_reported_provider_network_request_performed": True,
            "executor_reported_real_provider_api_called": True,
        }

    provider_execution = execute_live_provider_request_with_client(
        executor_readiness,
        invocation,
        provider_client,
        source_path=f"{config_model.source_path}/provider-execution",
    )
    report_state.update(
        provider_execution_status=provider_execution.status,
        provider_effect_receipt_sha256=(
            provider_execution.provider_effect_receipt_sha256
        ),
        external_provider_calls_performed=call_count > 0,
        credential_material_used_by_executor=call_count > 0,
    )
    if provider_execution.status != "provider_effect_receipt_emitted":
        return _build_report(
            config_model,
            status="blocked_provider_execution",
            blockers=list(provider_execution.blockers),
            **report_state,
        )

    effect_intake = build_provider_response_receipt_from_provider_effect_receipt(
        invocation,
        provider_execution.provider_effect_receipt or {},
        source_path=f"{config_model.source_path}/provider-effect-intake",
    )
    report_state.update(
        provider_effect_intake_status=effect_intake.status,
        provider_response_receipt_sha256=effect_intake.response_receipt_sha256,
    )
    if effect_intake.status != "provider_response_receipt_prepared":
        return _build_report(
            config_model,
            status="blocked_provider_execution",
            blockers=list(effect_intake.blockers),
            **report_state,
        )

    response_intake = build_live_observation_from_provider_response_receipt(
        request_readiness,
        effect_intake.response_receipt or {},
        provider_executor_invocation=invocation,
        source_path=f"{config_model.source_path}/provider-response-intake",
    )
    report_state["provider_response_intake_status"] = response_intake.status
    if response_intake.status != "live_observation_prepared":
        return _build_report(
            config_model,
            status="blocked_provider_execution",
            blockers=list(response_intake.blockers),
            **report_state,
        )

    return _build_report(
        config_model,
        status="cwa_live_chain_verified",
        connector_health_evidence_ready=True,
        live_provider_api_evidence_ready=True,
        **report_state,
    )


def write_cwa_live_qualification_report(
    report: CwaLiveQualificationReport,
    path: str | Path,
) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        report.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    return output_path


def load_cwa_live_qualification_report(
    path: str | Path,
) -> CwaLiveQualificationReport:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return CwaLiveQualificationReport.model_validate(payload)


def build_cwa_live_config_from_target_profile(
    profile: Mapping[str, Any],
    *,
    allow_live_provider_call: bool,
    execution_host_ref: str | None = None,
) -> CwaLiveQualificationConfig:
    runtime_target = _mapping(profile.get("runtime_target"))
    provider_target = _mapping(profile.get("provider_target"))
    route_context = _mapping(profile.get("route_context"))
    authorization = _mapping(profile.get("operator_authorization"))
    profile_source_path = str(profile.get("source_path", "")).rstrip("/")
    if not profile_source_path:
        raise ValueError("target profile source_path is required")
    if provider_target.get("provider_id") != "cwa_opendata":
        raise ValueError("target profile must select cwa_opendata")
    profile_authorized = authorization.get("cwa_live_read_authorized") is True
    run_id = profile_source_path.rsplit("/", 2)[-2] + "-cwa-live"
    return CwaLiveQualificationConfig(
        source_path=f"{profile_source_path}/cwa-live",
        run_id=run_id,
        execution_host_ref=(
            execution_host_ref
            or str(runtime_target.get("host_ref") or "prod://runtime/unknown")
        ),
        route_scope_ref=str(profile.get("route_scope_ref", "")),
        route_id=str(route_context.get("route_id", "")),
        segment_id=str(route_context.get("segment_id", "")),
        location_name=str(provider_target.get("location_name", "")),
        forecast_dataset_id=str(
            provider_target.get("forecast_dataset_id") or CWA_36H_FORECAST
        ),
        connector_id=str(provider_target.get("connector_id") or "connector.cwa.weather"),
        credential_ref=str(provider_target.get("credential_ref", "")),
        operator_identity_ref=str(authorization.get("operator_identity_ref", "")),
        operator_role=str(authorization.get("operator_role", "")),
        allow_live_provider_call=bool(
            allow_live_provider_call and profile_authorized
        ),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run a sanitized CWA live safety qualification chain."
    )
    parser.add_argument("--target-profile", required=True)
    parser.add_argument("--env-root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--execution-host-ref")
    parser.add_argument("--allow-live-cwa", action="store_true")
    args = parser.parse_args(argv)

    profile = json.loads(Path(args.target_profile).read_text(encoding="utf-8"))
    if not isinstance(profile, Mapping):
        raise ValueError("target profile must be a JSON object")
    config = build_cwa_live_config_from_target_profile(
        profile,
        allow_live_provider_call=args.allow_live_cwa,
        execution_host_ref=args.execution_host_ref,
    )
    live_env: dict[str, str] = dict(os.environ)
    load_scout_env_files(repo_root=Path(args.env_root), environ=live_env)
    report = run_cwa_live_qualification(config, env=live_env)
    write_cwa_live_qualification_report(report, args.output)
    print(
        json.dumps(
            {
                "status": report.status,
                "output": str(Path(args.output)),
                "credential_ref_resolved_without_value": (
                    report.credential_ref_resolved_without_value
                ),
                "connector_health_evidence_ready": (
                    report.connector_health_evidence_ready
                ),
                "live_provider_api_evidence_ready": (
                    report.live_provider_api_evidence_ready
                ),
            },
            sort_keys=True,
        )
    )
    return 0 if report.status == "cwa_live_chain_verified" else 2


def _build_provider_executor_manifest(
    config: CwaLiveQualificationConfig,
    request_readiness: Any,
) -> ProductionLiveProviderExecutorEffectBoundaryManifest:
    refs = {
        "provider_effect_boundary_ref": (
            f"attestation://provider-effect/cwa-weather/{config.run_id}/reviewed"
        ),
        "response_verifier_ref": (
            f"attestation://provider-response-verifier/cwa-weather/{config.run_id}"
        ),
        "freshness_attestor_ref": (
            f"attestation://freshness/cwa-weather/{config.run_id}"
        ),
        "field_device_validator_ref": (
            f"attestation://field-device/cwa-weather/{config.run_id}"
        ),
        "fallback_plan_ref": (
            f"attestation://provider-effect/cwa-weather/{config.run_id}/fallback"
        ),
    }
    return ProductionLiveProviderExecutorEffectBoundaryManifest(
        source_provider="cwa_provider_executor_review",
        source_path=(
            f"attestation://provider-effect/cwa-weather/{config.run_id}/executor-ready"
        ),
        gate_id=request_readiness.gate_id,
        connector_id=request_readiness.connector_id,
        provider_request_readiness_sha256=request_readiness.sha256,
        connector_manifest_sha256=request_readiness.manifest_sha256,
        request_contract_sha256=request_readiness.request_contract_sha256,
        source_observation_path=request_readiness.source_observation_path,
        route_scope_ref=request_readiness.route_scope_ref,
        connector_health_ref=request_readiness.connector_health_ref,
        connector_health_sha256=request_readiness.connector_health_sha256,
        credential_ref=config.credential_ref,
        provider_request_ref=request_readiness.provider_request_ref,
        provider_request_sha256=request_readiness.provider_request_sha256,
        provider_effect_boundary_ref=refs["provider_effect_boundary_ref"],
        provider_effect_boundary_sha256=_ref_sha256(
            config,
            "provider-effect-boundary",
            refs["provider_effect_boundary_ref"],
        ),
        response_verifier_ref=refs["response_verifier_ref"],
        response_verifier_sha256=_ref_sha256(
            config,
            "response-verifier",
            refs["response_verifier_ref"],
        ),
        freshness_attestor_ref=refs["freshness_attestor_ref"],
        freshness_attestor_sha256=_ref_sha256(
            config,
            "freshness-attestor",
            refs["freshness_attestor_ref"],
        ),
        field_device_validator_ref=refs["field_device_validator_ref"],
        field_device_validator_sha256=_ref_sha256(
            config,
            "field-device-validator",
            refs["field_device_validator_ref"],
        ),
        fallback_plan_ref=refs["fallback_plan_ref"],
        fallback_plan_sha256=_ref_sha256(
            config,
            "provider-fallback",
            refs["fallback_plan_ref"],
        ),
        idempotency_key=f"{config.run_id}-provider-readiness",
    )


def _build_provider_invocation_request(
    config: CwaLiveQualificationConfig,
    readiness: Any,
    *,
    operator_sha256: str,
) -> ProductionLiveProviderExecutorInvocationRequest:
    return ProductionLiveProviderExecutorInvocationRequest(
        gate_id=readiness.gate_id,
        connector_id=readiness.connector_id,
        provider_executor_readiness_sha256=readiness.sha256,
        provider_request_readiness_sha256=(
            readiness.provider_request_readiness_sha256
        ),
        provider_executor_manifest_sha256=(
            readiness.provider_executor_manifest_sha256
        ),
        connector_manifest_sha256=readiness.connector_manifest_sha256,
        request_contract_sha256=readiness.request_contract_sha256,
        source_observation_path=readiness.source_observation_path,
        route_scope_ref=readiness.route_scope_ref,
        provider_request_ref=readiness.provider_request_ref,
        provider_request_sha256=readiness.provider_request_sha256,
        provider_effect_boundary_ref=readiness.provider_effect_boundary_ref,
        provider_effect_boundary_sha256=(
            readiness.provider_effect_boundary_sha256
        ),
        response_verifier_ref=readiness.response_verifier_ref,
        response_verifier_sha256=readiness.response_verifier_sha256,
        freshness_attestor_ref=readiness.freshness_attestor_ref,
        freshness_attestor_sha256=readiness.freshness_attestor_sha256,
        field_device_validator_ref=readiness.field_device_validator_ref,
        field_device_validator_sha256=readiness.field_device_validator_sha256,
        fallback_plan_ref=readiness.fallback_plan_ref,
        fallback_plan_sha256=readiness.fallback_plan_sha256,
        operator_identity_ref=config.operator_identity_ref,
        operator_identity_sha256=operator_sha256,
        operator_role=config.operator_role,
        explicit_confirmation=True,
        confirmation_phrase="INVOKE SCOUT LIVE PROVIDER",
        idempotency_key=f"{config.run_id}-provider-invocation",
    )


def _safe_cwa_payload_summary(
    payload: Mapping[str, Any],
    *,
    dataset_id: str,
) -> dict[str, Any]:
    records = payload.get("records")
    records_mapping = records if isinstance(records, Mapping) else {}
    locations = records_mapping.get("location")
    return {
        "dataset_id": dataset_id,
        "provider_success": str(payload.get("success", "")).lower() == "true",
        "records_present": isinstance(records, Mapping),
        "location_count": len(locations) if isinstance(locations, list) else 0,
        "top_level_key_count": len(payload),
    }


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _ref_sha256(
    config: CwaLiveQualificationConfig,
    label: str,
    ref: str,
) -> str:
    return aggregate_sha256(
        [
            {
                "run_id": config.run_id,
                "label": label,
                "ref": ref,
                "execution_host_ref": config.execution_host_ref,
            }
        ]
    )


def _build_report(
    config: CwaLiveQualificationConfig,
    *,
    status: CwaLiveQualificationStatus,
    blockers: list[str] | None = None,
    **state: Any,
) -> CwaLiveQualificationReport:
    limitations = [
        "CWA live-chain evidence does not qualify resident freshness, field devices, "
        "Pi hardware, Phase 1 writer deployment, transport delivery, or cutover.",
        "Operator identity is an opaque local authorization reference, not external IAM proof.",
    ]
    payload = {
        "source_path": f"{config.source_path}/report",
        "status": status,
        "run_id": config.run_id,
        "execution_host_ref": config.execution_host_ref,
        "route_scope_ref": config.route_scope_ref,
        "dataset_id": config.forecast_dataset_id,
        "credential_ref": config.credential_ref,
        "blockers": blockers or [],
        "limitations": limitations,
        **state,
    }
    digest_payload = {
        **payload,
        "observed_at": payload["observed_at"].isoformat(),
    }
    digest = aggregate_sha256([digest_payload])
    return CwaLiveQualificationReport(sha256=digest, **payload)


if __name__ == "__main__":
    raise SystemExit(main())
