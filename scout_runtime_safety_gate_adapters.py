from __future__ import annotations

from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scout_energy_models import aggregate_sha256
from scout_runtime_safety_gate_models import (
    SafetyGateConfidence,
    SafetyGateRouteContext,
    build_runtime_safety_gate_event,
)


WeatherGateLevel = Literal["none", "watch", "advisory", "unsafe", "severe"]
EnvironmentThreatImmediacy = Literal["distant", "nearby", "immediate"]
EnvironmentThreatPassability = Literal["passable", "limited", "blocked", "unknown"]
ProductionLiveProviderGateId = Literal["weather_gate", "environment_threat_gate"]
ProductionLiveProviderHealthStatus = Literal["healthy", "degraded", "unknown"]
ProductionLiveProviderRequestMode = Literal[
    "dry_run",
    "provider_effect_boundary_request",
]
ProductionLiveProviderRequestStatus = Literal[
    "blocked_provider_request_lineage_mismatch",
    "blocked_connector_health_not_ready",
    "blocked_requires_credential_ref",
    "blocked_provider_effect_boundary_missing",
    "dry_run_ready",
    "provider_request_boundary_authorized",
]
ProductionLiveProviderResponseStatus = Literal["success", "partial", "failed", "unknown"]
ProductionLiveProviderResponseIntakeStatus = Literal[
    "blocked_provider_request_not_authorized",
    "blocked_provider_response_lineage_mismatch",
    "blocked_provider_executor_invocation_not_authorized",
    "blocked_provider_executor_invocation_lineage_mismatch",
    "blocked_missing_provider_evidence",
    "blocked_freshness_attestation_not_ready",
    "blocked_freshness_attestation_lineage_mismatch",
    "blocked_provider_response_not_successful",
    "blocked_provider_response_not_current",
    "blocked_field_device_validation_not_ready",
    "blocked_field_device_validation_lineage_mismatch",
    "live_observation_prepared",
]
ProductionLiveConnectorHealthIntakeStatus = Literal[
    "blocked_connector_health_invocation_not_authorized",
    "blocked_connector_health_invocation_lineage_mismatch",
    "blocked_connector_health_check_missing",
    "blocked_connector_health_evidence_missing",
    "blocked_connector_health_not_ready",
    "blocked_requires_credential_ref",
    "connector_manifest_prepared",
]
ProductionLiveConnectorHealthExecutorInvocationStatus = Literal[
    "blocked_connector_health_effect_boundary_missing",
    "blocked_requires_credential_ref",
    "blocked_connector_health_operator_identity_missing",
    "blocked_explicit_connector_health_confirmation_missing",
    "connector_health_executor_invocation_authorized",
]
ProductionLiveConnectorHealthExecutionStatus = Literal[
    "blocked_connector_health_invocation_not_authorized",
    "blocked_connector_health_client_result_invalid",
    "blocked_connector_health_client_effect_missing",
    "connector_health_receipt_emitted",
]
ProductionLiveFieldDeviceValidationStatus = Literal[
    "confirmed",
    "disputed",
    "unavailable",
    "unknown",
]
ProductionLiveFieldDeviceValidationIntakeStatus = Literal[
    "blocked_field_device_validator_invocation_not_authorized",
    "blocked_field_device_validator_invocation_lineage_mismatch",
    "blocked_field_device_validation_lineage_mismatch",
    "blocked_field_device_validation_evidence_missing",
    "blocked_field_device_validation_not_confirmed",
    "blocked_field_device_validation_not_current",
    "field_device_validation_prepared",
]
ProductionLiveFieldDeviceValidatorInvocationStatus = Literal[
    "blocked_field_device_validator_effect_boundary_missing",
    "blocked_field_device_validator_input_evidence_missing",
    "blocked_field_device_validator_operator_identity_missing",
    "blocked_explicit_field_device_validator_confirmation_missing",
    "field_device_validator_invocation_authorized",
]
ProductionLiveFieldDeviceValidationExecutionStatus = Literal[
    "blocked_field_device_validator_invocation_not_authorized",
    "blocked_field_device_client_result_invalid",
    "blocked_field_device_client_effect_missing",
    "field_device_validation_receipt_emitted",
]
ProductionLiveFreshnessAttestationStatus = Literal[
    "current",
    "stale",
    "unavailable",
    "unknown",
]
ProductionLiveFreshnessAttestationIntakeStatus = Literal[
    "blocked_freshness_attestor_invocation_not_authorized",
    "blocked_freshness_attestor_invocation_lineage_mismatch",
    "blocked_freshness_attestation_lineage_mismatch",
    "blocked_freshness_attestation_evidence_missing",
    "blocked_freshness_attestation_not_current",
    "freshness_attestation_prepared",
]
ProductionLiveFreshnessAttestorInvocationStatus = Literal[
    "blocked_freshness_attestor_effect_boundary_missing",
    "blocked_freshness_attestor_input_evidence_missing",
    "blocked_freshness_attestor_operator_identity_missing",
    "blocked_explicit_freshness_attestor_confirmation_missing",
    "freshness_attestor_invocation_authorized",
]
ProductionLiveFreshnessAttestationExecutionStatus = Literal[
    "blocked_freshness_attestor_invocation_not_authorized",
    "blocked_freshness_client_result_invalid",
    "blocked_freshness_client_effect_missing",
    "freshness_attestation_receipt_emitted",
]
ProductionLiveProviderExecutorReadinessStatus = Literal[
    "blocked_provider_request_not_authorized",
    "blocked_provider_executor_lineage_mismatch",
    "blocked_provider_executor_boundary_missing",
    "blocked_response_verifier_missing",
    "blocked_freshness_attestor_missing",
    "blocked_field_device_validator_missing",
    "blocked_fallback_plan_missing",
    "ready_for_reviewed_provider_effect_boundary",
]
ProductionLiveProviderExecutorInvocationStatus = Literal[
    "blocked_provider_executor_not_ready",
    "blocked_provider_invocation_lineage_mismatch",
    "blocked_provider_effect_boundary_missing",
    "blocked_provider_operator_identity_missing",
    "blocked_explicit_provider_invocation_confirmation_missing",
    "provider_executor_invocation_authorized",
]
ProductionLiveProviderEffectReceiptIntakeStatus = Literal[
    "blocked_provider_executor_invocation_not_authorized",
    "blocked_provider_effect_lineage_mismatch",
    "blocked_provider_effect_evidence_missing",
    "blocked_provider_effect_not_successful",
    "provider_response_receipt_prepared",
]
ProductionLiveProviderExecutionStatus = Literal[
    "blocked_provider_executor_not_ready",
    "blocked_provider_executor_invocation_not_authorized",
    "blocked_provider_execution_lineage_mismatch",
    "blocked_provider_client_result_invalid",
    "blocked_provider_client_effect_missing",
    "provider_effect_receipt_emitted",
]

_PRODUCTION_LIVE_SOURCE_PREFIXES = (
    "runtime://",
    "resident://",
    "prod://",
    "provider://",
    "cwa://",
    "weather://",
)
_PRODUCTION_LIVE_OBSERVATION_REF_PREFIXES = (
    *_PRODUCTION_LIVE_SOURCE_PREFIXES,
    "device://",
    "operator://",
    "field://",
)
_PRODUCTION_LIVE_ATTESTATION_PREFIXES = (
    "attestation://",
    "provider://",
    "cwa://",
    "field://",
    "device://",
    "operator://",
)
_PRODUCTION_SECRET_REF_PREFIXES = (
    "secret://",
    "vault://",
    "kms://",
    "keychain://",
    "envref://",
)
_CONNECTOR_HEALTH_EXECUTOR_INVOCATION_PHRASE = "INVOKE SCOUT CONNECTOR HEALTH"
_FRESHNESS_ATTESTOR_INVOCATION_PHRASE = "INVOKE SCOUT FRESHNESS ATTESTOR"
_FIELD_DEVICE_VALIDATOR_INVOCATION_PHRASE = "INVOKE SCOUT FIELD DEVICE VALIDATOR"
_LIVE_PROVIDER_EXECUTOR_INVOCATION_PHRASE = "INVOKE SCOUT LIVE PROVIDER"


class PaceGateObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_provider: str = "scout_runtime_fixture"
    source_path: str = "inline:pace-gate-observation"
    event_id: str = "pace_gate:fixture"
    observed_at_offset_s: int = Field(default=0, ge=0)
    observed_segment_minutes: float = Field(ge=0)
    reference_p75_segment_minutes: float = Field(gt=0)
    reference_max_segment_minutes: float | None = Field(default=None, gt=0)
    observed_pace_min_per_km: float | None = Field(default=None, gt=0)
    reference_p75_pace_min_per_km: float | None = Field(default=None, gt=0)
    low_movement_efficiency_ratio: float | None = Field(default=None, ge=0)
    route_pressure_review_required: bool = False
    route_context: SafetyGateRouteContext = Field(default_factory=SafetyGateRouteContext)
    evidence_refs: list[str] = Field(default_factory=list)
    confidence: SafetyGateConfidence = "medium"


class DelayGateObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_provider: str = "scout_runtime_fixture"
    source_path: str = "inline:delay-gate-observation"
    event_id: str = "delay_gate:fixture"
    observed_at_offset_s: int = Field(default=0, ge=0)
    delay_minutes: float
    planned_buffer_minutes: float | None = None
    checkpoint_deadline_missed: bool = False
    camp_deadline_missed: bool = False
    route_pressure_review_required: bool = False
    route_context: SafetyGateRouteContext = Field(default_factory=SafetyGateRouteContext)
    evidence_refs: list[str] = Field(default_factory=list)
    confidence: SafetyGateConfidence = "medium"


class DarknessGateObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_provider: str = "scout_runtime_fixture"
    source_path: str = "inline:darkness-gate-observation"
    event_id: str = "darkness_gate:fixture"
    observed_at_offset_s: int = Field(default=0, ge=0)
    daylight_buffer_minutes: float
    minutes_to_next_safe_objective: float = Field(ge=0)
    emergency_bivy_candidate_distance_m: float | None = Field(default=None, ge=0)
    route_pressure_review_required: bool = True
    route_context: SafetyGateRouteContext = Field(default_factory=SafetyGateRouteContext)
    evidence_refs: list[str] = Field(default_factory=list)
    confidence: SafetyGateConfidence = "medium"


class WeatherGateObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_provider: str = "scout_runtime_fixture"
    source_path: str = "inline:weather-gate-observation"
    event_id: str = "weather_gate:fixture"
    observed_at_offset_s: int = Field(default=0, ge=0)
    warning_level: WeatherGateLevel = "none"
    warning_type: str | None = None
    wind_risk: bool = False
    rain_risk: bool = False
    lightning_risk: bool = False
    source_age_minutes: float | None = Field(default=None, ge=0)
    route_pressure_review_required: bool = False
    route_context: SafetyGateRouteContext = Field(default_factory=SafetyGateRouteContext)
    evidence_refs: list[str] = Field(default_factory=list)
    confidence: SafetyGateConfidence = "medium"


class EnvironmentThreatGateObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_provider: str = "scout_runtime_fixture"
    source_path: str = "inline:environment-threat-gate-observation"
    event_id: str = "environment_threat_gate:fixture"
    observed_at_offset_s: int = Field(default=0, ge=0)
    threat_type: str
    passability: EnvironmentThreatPassability = "unknown"
    immediacy: EnvironmentThreatImmediacy = "nearby"
    route_blocked: bool = False
    safe_bypass_known: bool = False
    route_pressure_review_required: bool = True
    route_context: SafetyGateRouteContext = Field(default_factory=SafetyGateRouteContext)
    evidence_refs: list[str] = Field(default_factory=list)
    confidence: SafetyGateConfidence = "medium"

    @model_validator(mode="after")
    def normalize_blocked_passability(self) -> "EnvironmentThreatGateObservation":
        if self.route_blocked and self.passability == "passable":
            raise ValueError("route_blocked cannot be passable")
        return self


class ProductionLiveWeatherObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_production_live_weather_observation"
    artifact_version: str = "production_live_weather_observation.v0"
    source_provider: str = Field(min_length=1)
    source_path: str = Field(min_length=1)
    event_id: str = "weather_gate:production-live"
    observed_at_offset_s: int = Field(default=0, ge=0)
    warning_level: WeatherGateLevel = "none"
    warning_type: str | None = None
    wind_risk: bool = False
    rain_risk: bool = False
    lightning_risk: bool = False
    source_age_minutes: float = Field(ge=0)
    provider_dataset_ids: list[str] = Field(default_factory=list)
    provider_evidence_ref: str = Field(min_length=1)
    provider_request_ref: str | None = None
    provider_request_sha256: str | None = None
    freshness_attestation_ref: str = Field(min_length=1)
    route_scope_ref: str = Field(min_length=1)
    field_attestation_ref: str | None = None
    route_pressure_review_required: bool = False
    route_context: SafetyGateRouteContext = Field(default_factory=SafetyGateRouteContext)
    evidence_refs: list[str] = Field(default_factory=list)
    confidence: SafetyGateConfidence = "medium"
    adapter_network_request_performed: bool = False
    real_provider_api_called_by_adapter: bool = False
    runtime_ingest_performed_by_adapter: bool = False
    safety_api_called: bool = False
    phase1_l0_l4_state_mutated: bool = False

    @model_validator(mode="after")
    def enforce_live_weather_boundary(self) -> "ProductionLiveWeatherObservation":
        _assert_production_live_source(self.source_provider, self.source_path)
        _assert_ref_prefix(
            "provider_evidence_ref",
            self.provider_evidence_ref,
            _PRODUCTION_LIVE_OBSERVATION_REF_PREFIXES,
        )
        if self.provider_request_ref is not None:
            if self.provider_request_sha256 is None:
                raise ValueError("provider_request_ref requires provider_request_sha256")
            _assert_ref_prefix(
                "provider_request_ref",
                self.provider_request_ref,
                _PRODUCTION_LIVE_OBSERVATION_REF_PREFIXES,
            )
        elif self.provider_request_sha256 is not None:
            raise ValueError("provider_request_sha256 requires provider_request_ref")
        _assert_ref_prefix(
            "freshness_attestation_ref",
            self.freshness_attestation_ref,
            _PRODUCTION_LIVE_ATTESTATION_PREFIXES,
        )
        _assert_ref_prefix(
            "route_scope_ref",
            self.route_scope_ref,
            _PRODUCTION_LIVE_OBSERVATION_REF_PREFIXES,
        )
        if self.field_attestation_ref is not None:
            _assert_ref_prefix(
                "field_attestation_ref",
                self.field_attestation_ref,
                _PRODUCTION_LIVE_ATTESTATION_PREFIXES,
            )
        _assert_route_scope(self.route_context)
        _assert_no_adapter_effects(
            adapter_network_request_performed=self.adapter_network_request_performed,
            real_provider_api_called_by_adapter=self.real_provider_api_called_by_adapter,
            runtime_ingest_performed_by_adapter=self.runtime_ingest_performed_by_adapter,
            safety_api_called=self.safety_api_called,
            phase1_l0_l4_state_mutated=self.phase1_l0_l4_state_mutated,
        )
        return self


class ProductionLiveEnvironmentThreatObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_production_live_environment_threat_observation"
    artifact_version: str = "production_live_environment_threat_observation.v0"
    source_provider: str = Field(min_length=1)
    source_path: str = Field(min_length=1)
    event_id: str = "environment_threat_gate:production-live"
    observed_at_offset_s: int = Field(default=0, ge=0)
    threat_type: str = Field(min_length=1)
    passability: EnvironmentThreatPassability = "unknown"
    immediacy: EnvironmentThreatImmediacy = "nearby"
    route_blocked: bool = False
    safe_bypass_known: bool = False
    current_observation_ref: str = Field(min_length=1)
    provider_request_ref: str | None = None
    provider_request_sha256: str | None = None
    freshness_attestation_ref: str = Field(min_length=1)
    route_scope_ref: str = Field(min_length=1)
    provider_evidence_ref: str | None = None
    field_attestation_ref: str | None = None
    device_evidence_ref: str | None = None
    route_pressure_review_required: bool = True
    route_context: SafetyGateRouteContext = Field(default_factory=SafetyGateRouteContext)
    evidence_refs: list[str] = Field(default_factory=list)
    confidence: SafetyGateConfidence = "medium"
    adapter_network_request_performed: bool = False
    real_provider_api_called_by_adapter: bool = False
    runtime_ingest_performed_by_adapter: bool = False
    safety_api_called: bool = False
    phase1_l0_l4_state_mutated: bool = False

    @model_validator(mode="after")
    def enforce_live_threat_boundary(
        self,
    ) -> "ProductionLiveEnvironmentThreatObservation":
        if self.route_blocked and self.passability == "passable":
            raise ValueError("route_blocked cannot be passable")
        _assert_production_live_source(self.source_provider, self.source_path)
        _assert_ref_prefix(
            "current_observation_ref",
            self.current_observation_ref,
            _PRODUCTION_LIVE_OBSERVATION_REF_PREFIXES,
        )
        if self.provider_request_ref is not None:
            if self.provider_request_sha256 is None:
                raise ValueError("provider_request_ref requires provider_request_sha256")
            _assert_ref_prefix(
                "provider_request_ref",
                self.provider_request_ref,
                _PRODUCTION_LIVE_OBSERVATION_REF_PREFIXES,
            )
        elif self.provider_request_sha256 is not None:
            raise ValueError("provider_request_sha256 requires provider_request_ref")
        _assert_ref_prefix(
            "freshness_attestation_ref",
            self.freshness_attestation_ref,
            _PRODUCTION_LIVE_ATTESTATION_PREFIXES,
        )
        _assert_ref_prefix(
            "route_scope_ref",
            self.route_scope_ref,
            _PRODUCTION_LIVE_OBSERVATION_REF_PREFIXES,
        )
        if not (
            self.provider_evidence_ref
            or self.field_attestation_ref
            or self.device_evidence_ref
        ):
            raise ValueError(
                "environment threat live observation requires provider, field, or device evidence"
            )
        for field_name, value in (
            ("provider_evidence_ref", self.provider_evidence_ref),
            ("field_attestation_ref", self.field_attestation_ref),
            ("device_evidence_ref", self.device_evidence_ref),
        ):
            if value is not None:
                _assert_ref_prefix(
                    field_name,
                    value,
                    _PRODUCTION_LIVE_ATTESTATION_PREFIXES,
                )
        _assert_route_scope(self.route_context)
        _assert_no_adapter_effects(
            adapter_network_request_performed=self.adapter_network_request_performed,
            real_provider_api_called_by_adapter=self.real_provider_api_called_by_adapter,
            runtime_ingest_performed_by_adapter=self.runtime_ingest_performed_by_adapter,
            safety_api_called=self.safety_api_called,
            phase1_l0_l4_state_mutated=self.phase1_l0_l4_state_mutated,
        )
        return self


class ProductionLiveProviderConnectorManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_production_live_provider_connector_manifest"
    artifact_version: str = "production_live_provider_connector_manifest.v0"
    gate_id: ProductionLiveProviderGateId
    connector_id: str = Field(min_length=1)
    provider_name: str = Field(min_length=1)
    source_provider: str = Field(min_length=1)
    source_path: str = Field(min_length=1)
    provider_dataset_ids: list[str] = Field(default_factory=list)
    route_scope_ref: str = Field(min_length=1)
    health_status: ProductionLiveProviderHealthStatus = "unknown"
    connector_health_ref: str | None = None
    connector_health_sha256: str | None = None
    credential_ref: str | None = None
    freshness_requirement_minutes: int = Field(default=180, gt=0)
    route_scoped_request_supported: bool = True
    freshness_attestation_supported: bool = True
    effect_boundary_required: bool = True
    manifest_network_request_performed: bool = False
    real_provider_api_called_by_manifest: bool = False
    runtime_ingest_performed_by_manifest: bool = False
    safety_api_called: bool = False
    phase1_l0_l4_state_mutated: bool = False
    credential_material_embedded: bool = False
    raw_location_payload_embedded: bool = False

    @model_validator(mode="after")
    def enforce_connector_manifest(self) -> "ProductionLiveProviderConnectorManifest":
        _assert_production_live_source(self.source_provider, self.source_path)
        _assert_ref_prefix(
            "route_scope_ref",
            self.route_scope_ref,
            _PRODUCTION_LIVE_OBSERVATION_REF_PREFIXES,
        )
        if self.connector_health_ref is not None:
            _assert_ref_prefix(
                "connector_health_ref",
                self.connector_health_ref,
                _PRODUCTION_LIVE_ATTESTATION_PREFIXES,
            )
        if self.credential_ref is not None:
            _assert_secret_ref(self.credential_ref)
        if (
            self.manifest_network_request_performed
            or self.real_provider_api_called_by_manifest
            or self.runtime_ingest_performed_by_manifest
            or self.safety_api_called
            or self.phase1_l0_l4_state_mutated
        ):
            raise ValueError("live provider connector manifest cannot perform effects")
        if self.credential_material_embedded:
            raise ValueError("live provider connector manifest cannot embed credentials")
        if self.raw_location_payload_embedded:
            raise ValueError(
                "live provider connector manifest cannot embed raw location payloads"
            )
        return self


class ProductionLiveProviderRequestContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_production_live_provider_request_contract"
    artifact_version: str = "production_live_provider_request_contract.v0"
    gate_id: ProductionLiveProviderGateId
    connector_id: str = Field(min_length=1)
    source_provider: str = Field(min_length=1)
    source_path: str = Field(min_length=1)
    route_scope_ref: str = Field(min_length=1)
    connector_health_ref: str | None = None
    connector_health_sha256: str | None = None
    credential_ref: str | None = None
    idempotency_key: str = Field(min_length=1)
    freshness_requirement_minutes: int = Field(default=180, gt=0)
    execution_mode: ProductionLiveProviderRequestMode = "dry_run"
    reviewed_provider_effect_boundary_ref: str | None = None
    reviewed_provider_effect_boundary_sha256: str | None = None
    request_network_call_performed: bool = False
    real_provider_api_called_by_request: bool = False
    runtime_ingest_performed_by_request: bool = False
    safety_api_called: bool = False
    phase1_l0_l4_state_mutated: bool = False
    credential_material_embedded: bool = False
    raw_location_payload_embedded: bool = False

    @model_validator(mode="after")
    def enforce_provider_request_contract(
        self,
    ) -> "ProductionLiveProviderRequestContract":
        _assert_production_live_source(self.source_provider, self.source_path)
        _assert_ref_prefix(
            "route_scope_ref",
            self.route_scope_ref,
            _PRODUCTION_LIVE_OBSERVATION_REF_PREFIXES,
        )
        if self.connector_health_ref is not None:
            _assert_ref_prefix(
                "connector_health_ref",
                self.connector_health_ref,
                _PRODUCTION_LIVE_ATTESTATION_PREFIXES,
            )
        if self.credential_ref is not None:
            _assert_secret_ref(self.credential_ref)
        if self.reviewed_provider_effect_boundary_ref is not None:
            if self.reviewed_provider_effect_boundary_sha256 is None:
                raise ValueError("reviewed_provider_effect_boundary_ref requires sha256")
            _assert_ref_prefix(
                "reviewed_provider_effect_boundary_ref",
                self.reviewed_provider_effect_boundary_ref,
                _PRODUCTION_LIVE_ATTESTATION_PREFIXES,
            )
        elif self.reviewed_provider_effect_boundary_sha256 is not None:
            raise ValueError("reviewed_provider_effect_boundary_sha256 requires ref")
        if (
            self.request_network_call_performed
            or self.real_provider_api_called_by_request
            or self.runtime_ingest_performed_by_request
            or self.safety_api_called
            or self.phase1_l0_l4_state_mutated
        ):
            raise ValueError("live provider request contract cannot perform effects")
        if self.credential_material_embedded:
            raise ValueError("live provider request contract cannot embed credentials")
        if self.raw_location_payload_embedded:
            raise ValueError(
                "live provider request contract cannot embed raw location payloads"
            )
        return self


class ProductionLiveProviderRequestReadinessReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_production_live_provider_request_readiness"
    artifact_version: str = "production_live_provider_request_readiness.v0"
    source_provider: str = "scout_runtime_safety_gate_adapters"
    source_path: str
    sha256: str
    status: ProductionLiveProviderRequestStatus
    gate_id: ProductionLiveProviderGateId
    connector_id: str
    manifest_sha256: str
    request_contract_sha256: str
    source_observation_path: str
    route_scope_ref: str
    freshness_requirement_minutes: int = Field(default=180, gt=0)
    connector_health_ref: str | None = None
    connector_health_sha256: str | None = None
    credential_ref_present: bool = False
    request_contract_prepared: bool = False
    provider_request_boundary_authorized: bool = False
    provider_request_ref: str | None = None
    provider_request_sha256: str | None = None
    execution_mode: ProductionLiveProviderRequestMode
    blockers: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    connector_health_checked_by_guard: bool = False
    provider_network_request_performed: bool = False
    real_provider_api_called: bool = False
    runtime_ingest_performed: bool = False
    safety_api_called: bool = False
    phase1_l0_l4_state_mutated: bool = False
    credential_material_embedded: bool = False
    raw_location_payload_embedded: bool = False

    @model_validator(mode="after")
    def enforce_readiness_receipt(
        self,
    ) -> "ProductionLiveProviderRequestReadinessReceipt":
        if self.request_contract_prepared != (
            self.status
            in {"dry_run_ready", "provider_request_boundary_authorized"}
        ):
            raise ValueError("request_contract_prepared must match status")
        if self.provider_request_boundary_authorized != (
            self.status == "provider_request_boundary_authorized"
        ):
            raise ValueError("provider_request_boundary_authorized must match status")
        if self.provider_request_boundary_authorized and not (
            self.provider_request_ref and self.provider_request_sha256
        ):
            raise ValueError("authorized provider request requires ref and sha256")
        if self.provider_request_ref is not None:
            _assert_ref_prefix(
                "provider_request_ref",
                self.provider_request_ref,
                _PRODUCTION_LIVE_OBSERVATION_REF_PREFIXES,
            )
        if (
            self.connector_health_checked_by_guard
            or self.provider_network_request_performed
            or self.real_provider_api_called
            or self.runtime_ingest_performed
            or self.safety_api_called
            or self.phase1_l0_l4_state_mutated
        ):
            raise ValueError("provider request readiness receipt cannot perform effects")
        if self.credential_material_embedded:
            raise ValueError("provider request readiness receipt cannot embed credentials")
        if self.raw_location_payload_embedded:
            raise ValueError(
                "provider request readiness receipt cannot embed raw location payloads"
            )
        return self


class ProductionLiveProviderResponseIntakeBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deterministic_intake_only: bool = True
    connector_health_checked_by_intake: bool = False
    provider_network_request_performed_by_intake: bool = False
    real_provider_api_called_by_intake: bool = False
    runtime_ingest_performed_by_intake: bool = False
    safety_api_called: bool = False
    phase1_l0_l4_state_mutated: bool = False
    credential_material_embedded: bool = False
    raw_location_payload_embedded: bool = False
    raw_provider_payload_embedded: bool = False

    @model_validator(mode="after")
    def enforce_provider_response_intake_boundary(
        self,
    ) -> "ProductionLiveProviderResponseIntakeBoundary":
        if not self.deterministic_intake_only:
            raise ValueError("provider response intake must be deterministic")
        if (
            self.connector_health_checked_by_intake
            or self.provider_network_request_performed_by_intake
            or self.real_provider_api_called_by_intake
            or self.runtime_ingest_performed_by_intake
            or self.safety_api_called
            or self.phase1_l0_l4_state_mutated
        ):
            raise ValueError("provider response intake cannot perform effects")
        if self.credential_material_embedded:
            raise ValueError("provider response intake cannot embed credentials")
        if self.raw_location_payload_embedded or self.raw_provider_payload_embedded:
            raise ValueError("provider response intake cannot embed raw payloads")
        return self


class ProductionLiveProviderResponseReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_production_live_provider_response_receipt"
    artifact_version: str = "production_live_provider_response_receipt.v0"
    source_provider: str = Field(min_length=1)
    source_path: str = Field(min_length=1)
    gate_id: ProductionLiveProviderGateId
    connector_id: str = Field(min_length=1)
    provider_request_readiness_sha256: str = Field(min_length=1)
    manifest_sha256: str = Field(min_length=1)
    request_contract_sha256: str = Field(min_length=1)
    source_observation_path: str = Field(min_length=1)
    route_scope_ref: str = Field(min_length=1)
    provider_request_ref: str = Field(min_length=1)
    provider_request_sha256: str = Field(min_length=1)
    provider_executor_invocation_sha256: str | None = None
    provider_execution_ref: str | None = None
    provider_execution_sha256: str | None = None
    provider_dataset_ids: list[str] = Field(default_factory=list)
    provider_evidence_ref: str | None = None
    provider_evidence_sha256: str | None = None
    current_observation_ref: str | None = None
    freshness_attestation_ref: str | None = None
    freshness_attestation_sha256: str | None = None
    source_age_minutes: float = Field(ge=0)
    freshness_requirement_minutes: int = Field(default=180, gt=0)
    response_status: ProductionLiveProviderResponseStatus = "unknown"
    observed_at_offset_s: int = Field(default=0, ge=0)
    warning_level: WeatherGateLevel = "none"
    warning_type: str | None = None
    wind_risk: bool = False
    rain_risk: bool = False
    lightning_risk: bool = False
    threat_type: str | None = None
    passability: EnvironmentThreatPassability = "unknown"
    immediacy: EnvironmentThreatImmediacy = "nearby"
    route_blocked: bool = False
    safe_bypass_known: bool = False
    field_attestation_ref: str | None = None
    device_evidence_ref: str | None = None
    route_pressure_review_required: bool = False
    route_context: SafetyGateRouteContext = Field(default_factory=SafetyGateRouteContext)
    evidence_refs: list[str] = Field(default_factory=list)
    confidence: SafetyGateConfidence = "medium"
    executor_reported_provider_network_request_performed: bool = False
    executor_reported_real_provider_api_called: bool = False
    executor_reported_runtime_ingest_performed: bool = False
    executor_reported_safety_api_called: bool = False
    executor_reported_phase1_l0_l4_state_mutated: bool = False
    credential_material_embedded: bool = False
    raw_location_payload_embedded: bool = False
    raw_provider_payload_embedded: bool = False

    @model_validator(mode="after")
    def enforce_provider_response_receipt(
        self,
    ) -> "ProductionLiveProviderResponseReceipt":
        if self.route_blocked and self.passability == "passable":
            raise ValueError("route_blocked cannot be passable")
        _assert_production_live_source(self.source_provider, self.source_path)
        _assert_production_live_source(
            self.source_provider,
            self.source_observation_path,
        )
        _assert_ref_prefix(
            "route_scope_ref",
            self.route_scope_ref,
            _PRODUCTION_LIVE_OBSERVATION_REF_PREFIXES,
        )
        _assert_ref_prefix(
            "provider_request_ref",
            self.provider_request_ref,
            _PRODUCTION_LIVE_OBSERVATION_REF_PREFIXES,
        )
        if self.provider_execution_ref is not None:
            _assert_ref_prefix(
                "provider_execution_ref",
                self.provider_execution_ref,
                _PRODUCTION_LIVE_OBSERVATION_REF_PREFIXES,
            )
        if (self.provider_execution_ref is None) != (
            self.provider_execution_sha256 is None
        ):
            raise ValueError("provider_execution_ref and sha256 must be paired")
        if self.provider_evidence_ref is not None:
            _assert_ref_prefix(
                "provider_evidence_ref",
                self.provider_evidence_ref,
                _PRODUCTION_LIVE_OBSERVATION_REF_PREFIXES,
            )
        if self.current_observation_ref is not None:
            _assert_ref_prefix(
                "current_observation_ref",
                self.current_observation_ref,
                _PRODUCTION_LIVE_OBSERVATION_REF_PREFIXES,
            )
        if self.freshness_attestation_ref is not None:
            _assert_ref_prefix(
                "freshness_attestation_ref",
                self.freshness_attestation_ref,
                _PRODUCTION_LIVE_ATTESTATION_PREFIXES,
            )
        if self.field_attestation_ref is not None:
            _assert_ref_prefix(
                "field_attestation_ref",
                self.field_attestation_ref,
                _PRODUCTION_LIVE_ATTESTATION_PREFIXES,
            )
        if self.device_evidence_ref is not None:
            _assert_ref_prefix(
                "device_evidence_ref",
                self.device_evidence_ref,
                _PRODUCTION_LIVE_OBSERVATION_REF_PREFIXES,
            )
        _assert_route_scope(self.route_context)
        if self.gate_id == "environment_threat_gate" and not (
            self.threat_type and self.current_observation_ref
        ):
            raise ValueError(
                "environment threat provider response requires threat_type and current_observation_ref"
            )
        if (
            self.executor_reported_runtime_ingest_performed
            or self.executor_reported_safety_api_called
            or self.executor_reported_phase1_l0_l4_state_mutated
        ):
            raise ValueError("provider response receipt cannot claim runtime effects")
        if self.credential_material_embedded:
            raise ValueError("provider response receipt cannot embed credentials")
        if self.raw_location_payload_embedded or self.raw_provider_payload_embedded:
            raise ValueError("provider response receipt cannot embed raw payloads")
        return self


class ProductionLiveProviderResponseIntakeDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_production_live_provider_response_intake"
    artifact_version: str = "production_live_provider_response_intake.v0"
    source_provider: str = "scout_runtime_safety_gate_adapters"
    source_path: str
    sha256: str
    status: ProductionLiveProviderResponseIntakeStatus
    gate_id: ProductionLiveProviderGateId
    connector_id: str
    request_readiness_sha256: str
    response_receipt_sha256: str
    live_observation_sha256: str | None = None
    provider_executor_invocation_sha256: str | None = None
    provider_execution_ref: str | None = None
    provider_execution_sha256: str | None = None
    manifest_sha256: str
    request_contract_sha256: str
    source_observation_path: str
    route_scope_ref: str
    provider_request_ref: str | None = None
    provider_request_sha256: str | None = None
    provider_evidence_ref: str | None = None
    provider_evidence_sha256: str | None = None
    freshness_attestation_ref: str | None = None
    freshness_attestation_sha256: str | None = None
    field_device_validation_sha256: str | None = None
    field_device_validation_present: bool = False
    field_attestation_ref: str | None = None
    field_attestation_sha256: str | None = None
    device_evidence_ref: str | None = None
    device_evidence_sha256: str | None = None
    source_age_minutes: float = Field(ge=0)
    freshness_requirement_minutes: int = Field(gt=0)
    provider_response_successful: bool = False
    provider_response_current: bool = False
    provider_executor_invocation_authorized: bool = False
    provider_executor_invocation_lineage_match: bool = False
    live_observation_prepared: bool = False
    weather_observation: ProductionLiveWeatherObservation | None = None
    environment_threat_observation: (
        ProductionLiveEnvironmentThreatObservation | None
    ) = None
    executor_reported_provider_network_request_performed: bool = False
    executor_reported_real_provider_api_called: bool = False
    intake_verified_live_safety_truth: bool = False
    connector_health_checked_by_intake: bool = False
    provider_network_request_performed_by_intake: bool = False
    real_provider_api_called_by_intake: bool = False
    runtime_ingest_performed_by_intake: bool = False
    safety_api_called: bool = False
    phase1_l0_l4_state_mutated: bool = False
    blockers: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    boundary: ProductionLiveProviderResponseIntakeBoundary = Field(
        default_factory=ProductionLiveProviderResponseIntakeBoundary
    )

    @model_validator(mode="after")
    def enforce_provider_response_intake(
        self,
    ) -> "ProductionLiveProviderResponseIntakeDecision":
        prepared = self.status == "live_observation_prepared"
        if self.live_observation_prepared != prepared:
            raise ValueError("live_observation_prepared must match status")
        if self.intake_verified_live_safety_truth:
            raise ValueError("provider response intake cannot verify safety truth")
        prepared_observation_count = int(self.weather_observation is not None) + int(
            self.environment_threat_observation is not None
        )
        if prepared and not (
            prepared_observation_count == 1 and self.live_observation_sha256
        ):
            raise ValueError("prepared provider response requires one observation")
        if not prepared and (
            prepared_observation_count > 0 or self.live_observation_sha256
        ):
            raise ValueError("blocked provider response cannot include an observation")
        if prepared and self.gate_id == "weather_gate" and not self.weather_observation:
            raise ValueError("weather response must prepare a weather observation")
        if (
            prepared
            and self.gate_id == "environment_threat_gate"
            and not self.environment_threat_observation
        ):
            raise ValueError("threat response must prepare a threat observation")
        if (
            self.connector_health_checked_by_intake
            or self.provider_network_request_performed_by_intake
            or self.real_provider_api_called_by_intake
            or self.runtime_ingest_performed_by_intake
            or self.safety_api_called
            or self.phase1_l0_l4_state_mutated
        ):
            raise ValueError("provider response intake cannot perform effects")
        return self


class ProductionLiveConnectorHealthIntakeBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deterministic_intake_only: bool = True
    connector_health_checked_by_intake: bool = False
    provider_network_request_performed_by_intake: bool = False
    real_provider_api_called_by_intake: bool = False
    runtime_ingest_performed_by_intake: bool = False
    safety_api_called: bool = False
    phase1_l0_l4_state_mutated: bool = False
    credential_material_embedded: bool = False
    raw_location_payload_embedded: bool = False
    raw_provider_payload_embedded: bool = False

    @model_validator(mode="after")
    def enforce_connector_health_intake_boundary(
        self,
    ) -> "ProductionLiveConnectorHealthIntakeBoundary":
        if not self.deterministic_intake_only:
            raise ValueError("connector health intake must be deterministic")
        if (
            self.connector_health_checked_by_intake
            or self.provider_network_request_performed_by_intake
            or self.real_provider_api_called_by_intake
            or self.runtime_ingest_performed_by_intake
            or self.safety_api_called
            or self.phase1_l0_l4_state_mutated
        ):
            raise ValueError("connector health intake cannot perform effects")
        if self.credential_material_embedded:
            raise ValueError("connector health intake cannot embed credentials")
        if self.raw_location_payload_embedded or self.raw_provider_payload_embedded:
            raise ValueError("connector health intake cannot embed raw payloads")
        return self


class ProductionLiveConnectorHealthExecutorInvocationBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deterministic_invocation_guard_only: bool = True
    connector_health_checked_by_guard: bool = False
    provider_network_request_performed_by_guard: bool = False
    real_provider_api_called_by_guard: bool = False
    runtime_ingest_performed_by_guard: bool = False
    safety_api_called: bool = False
    phase1_l0_l4_state_mutated: bool = False
    credential_material_embedded: bool = False
    raw_location_payload_embedded: bool = False
    raw_provider_payload_embedded: bool = False

    @model_validator(mode="after")
    def enforce_connector_health_executor_invocation_boundary(
        self,
    ) -> "ProductionLiveConnectorHealthExecutorInvocationBoundary":
        if not self.deterministic_invocation_guard_only:
            raise ValueError("connector health invocation guard must be deterministic")
        if (
            self.connector_health_checked_by_guard
            or self.provider_network_request_performed_by_guard
            or self.real_provider_api_called_by_guard
            or self.runtime_ingest_performed_by_guard
            or self.safety_api_called
            or self.phase1_l0_l4_state_mutated
        ):
            raise ValueError("connector health invocation guard cannot perform effects")
        if self.credential_material_embedded:
            raise ValueError("connector health invocation guard cannot embed credentials")
        if self.raw_location_payload_embedded or self.raw_provider_payload_embedded:
            raise ValueError("connector health invocation guard cannot embed raw payloads")
        return self


class ProductionLiveConnectorHealthExecutorInvocationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = (
        "scout_production_live_connector_health_executor_invocation_request"
    )
    artifact_version: str = (
        "production_live_connector_health_executor_invocation_request.v0"
    )
    gate_id: ProductionLiveProviderGateId
    connector_id: str = Field(min_length=1)
    provider_name: str = Field(min_length=1)
    source_provider: str = Field(min_length=1)
    source_path: str = Field(min_length=1)
    provider_dataset_ids: list[str] = Field(default_factory=list)
    route_scope_ref: str = Field(min_length=1)
    credential_ref: str | None = None
    freshness_requirement_minutes: int = Field(default=180, gt=0)
    reviewed_connector_health_effect_boundary_ref: str | None = None
    reviewed_connector_health_effect_boundary_sha256: str | None = None
    fallback_plan_ref: str | None = None
    fallback_plan_sha256: str | None = None
    operator_identity_ref: str | None = None
    operator_identity_sha256: str | None = None
    operator_role: str | None = None
    explicit_confirmation: bool = False
    confirmation_phrase: str | None = None
    idempotency_key: str = Field(min_length=1, max_length=128)
    connector_health_checked_by_guard: bool = False
    provider_network_request_performed_by_guard: bool = False
    real_provider_api_called_by_guard: bool = False
    runtime_ingest_performed_by_guard: bool = False
    safety_api_called: bool = False
    phase1_l0_l4_state_mutated: bool = False
    credential_material_embedded: bool = False
    raw_location_payload_embedded: bool = False
    raw_provider_payload_embedded: bool = False

    @model_validator(mode="after")
    def enforce_connector_health_invocation_request(
        self,
    ) -> "ProductionLiveConnectorHealthExecutorInvocationRequest":
        _assert_production_live_source(self.source_provider, self.source_path)
        _assert_ref_prefix(
            "route_scope_ref",
            self.route_scope_ref,
            _PRODUCTION_LIVE_OBSERVATION_REF_PREFIXES,
        )
        if self.credential_ref is not None:
            _assert_secret_ref(self.credential_ref)
        for field_name, value in (
            (
                "reviewed_connector_health_effect_boundary_ref",
                self.reviewed_connector_health_effect_boundary_ref,
            ),
            ("fallback_plan_ref", self.fallback_plan_ref),
            ("operator_identity_ref", self.operator_identity_ref),
        ):
            if value is not None:
                _assert_ref_prefix(
                    field_name,
                    value,
                    _PRODUCTION_LIVE_ATTESTATION_PREFIXES,
                )
        if (
            self.reviewed_connector_health_effect_boundary_ref is None
        ) != (self.reviewed_connector_health_effect_boundary_sha256 is None):
            raise ValueError("connector health effect boundary ref and sha256 must be paired")
        if (self.fallback_plan_ref is None) != (self.fallback_plan_sha256 is None):
            raise ValueError("fallback plan ref and sha256 must be paired")
        if (self.operator_identity_ref is None) != (
            self.operator_identity_sha256 is None
        ):
            raise ValueError("operator identity ref and sha256 must be paired")
        if (
            self.connector_health_checked_by_guard
            or self.provider_network_request_performed_by_guard
            or self.real_provider_api_called_by_guard
            or self.runtime_ingest_performed_by_guard
            or self.safety_api_called
            or self.phase1_l0_l4_state_mutated
        ):
            raise ValueError("connector health invocation request cannot perform effects")
        if self.credential_material_embedded:
            raise ValueError("connector health invocation request cannot embed credentials")
        if self.raw_location_payload_embedded or self.raw_provider_payload_embedded:
            raise ValueError("connector health invocation request cannot embed raw payloads")
        return self


class ProductionLiveConnectorHealthExecutorInvocationReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = (
        "scout_production_live_connector_health_executor_invocation_receipt"
    )
    artifact_version: str = (
        "production_live_connector_health_executor_invocation_receipt.v0"
    )
    source_provider: str = "scout_runtime_safety_gate_adapters"
    source_path: str
    sha256: str
    status: ProductionLiveConnectorHealthExecutorInvocationStatus
    gate_id: ProductionLiveProviderGateId
    connector_id: str
    provider_name: str
    source_observation_path: str
    route_scope_ref: str
    connector_health_invocation_request_sha256: str
    provider_dataset_ids: list[str] = Field(default_factory=list)
    reviewed_connector_health_effect_boundary_ref: str | None = None
    reviewed_connector_health_effect_boundary_sha256: str | None = None
    fallback_plan_ref: str | None = None
    fallback_plan_sha256: str | None = None
    credential_ref: str | None = None
    credential_ref_present: bool = False
    operator_identity_ref: str | None = None
    operator_identity_sha256: str | None = None
    operator_role: str | None = None
    idempotency_key: str
    connector_health_execution_ref: str | None = None
    connector_health_execution_sha256: str | None = None
    connector_health_effect_boundary_present: bool = False
    fallback_plan_present: bool = False
    operator_identity_present: bool = False
    explicit_confirmation_present: bool = False
    connector_health_executor_invocation_authorized: bool = False
    connector_health_checked_by_guard: bool = False
    provider_network_request_performed_by_guard: bool = False
    real_provider_api_called_by_guard: bool = False
    runtime_ingest_performed_by_guard: bool = False
    safety_api_called: bool = False
    phase1_l0_l4_state_mutated: bool = False
    blockers: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    boundary: ProductionLiveConnectorHealthExecutorInvocationBoundary = Field(
        default_factory=ProductionLiveConnectorHealthExecutorInvocationBoundary
    )

    @model_validator(mode="after")
    def enforce_connector_health_invocation_receipt(
        self,
    ) -> "ProductionLiveConnectorHealthExecutorInvocationReceipt":
        authorized = self.status == "connector_health_executor_invocation_authorized"
        if self.connector_health_executor_invocation_authorized != authorized:
            raise ValueError("connector health invocation authorization must match status")
        if authorized and not (
            self.connector_health_effect_boundary_present
            and self.fallback_plan_present
            and self.credential_ref_present
            and self.operator_identity_present
            and self.explicit_confirmation_present
            and self.connector_health_execution_ref
            and self.connector_health_execution_sha256
        ):
            raise ValueError("authorized connector health invocation requires all gates")
        if self.connector_health_execution_ref is not None:
            _assert_ref_prefix(
                "connector_health_execution_ref",
                self.connector_health_execution_ref,
                _PRODUCTION_LIVE_OBSERVATION_REF_PREFIXES,
            )
        if self.credential_ref is not None:
            _assert_secret_ref(self.credential_ref)
        if (
            self.connector_health_checked_by_guard
            or self.provider_network_request_performed_by_guard
            or self.real_provider_api_called_by_guard
            or self.runtime_ingest_performed_by_guard
            or self.safety_api_called
            or self.phase1_l0_l4_state_mutated
        ):
            raise ValueError("connector health invocation receipt cannot perform effects")
        return self


class ProductionLiveConnectorHealthExecutionBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reviewed_connector_health_effect_boundary_required: bool = True
    injected_connector_health_client_required: bool = True
    connector_health_check_allowed: bool = True
    provider_network_request_allowed: bool = True
    real_provider_api_call_allowed: bool = True
    runtime_ingest_performed_by_executor: bool = False
    safety_api_called: bool = False
    phase1_l0_l4_state_mutated: bool = False
    outbound_transport_invoked: bool = False
    hardware_control_performed: bool = False
    credential_material_embedded: bool = False
    raw_location_payload_embedded: bool = False
    raw_provider_payload_embedded: bool = False

    @model_validator(mode="after")
    def enforce_connector_health_execution_boundary(
        self,
    ) -> "ProductionLiveConnectorHealthExecutionBoundary":
        if not self.reviewed_connector_health_effect_boundary_required:
            raise ValueError("connector health executor requires a reviewed effect boundary")
        if not self.injected_connector_health_client_required:
            raise ValueError("connector health executor requires an injected client")
        if not (
            self.connector_health_check_allowed
            and self.provider_network_request_allowed
            and self.real_provider_api_call_allowed
        ):
            raise ValueError("connector health boundary must allow only provider health effects")
        if (
            self.runtime_ingest_performed_by_executor
            or self.safety_api_called
            or self.phase1_l0_l4_state_mutated
            or self.outbound_transport_invoked
            or self.hardware_control_performed
        ):
            raise ValueError("connector health executor boundary cannot perform runtime effects")
        if self.credential_material_embedded:
            raise ValueError("connector health executor boundary cannot embed credentials")
        if self.raw_location_payload_embedded or self.raw_provider_payload_embedded:
            raise ValueError("connector health executor boundary cannot embed raw payloads")
        return self


class ProductionLiveConnectorHealthExecutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_production_live_connector_health_execution_request"
    artifact_version: str = "production_live_connector_health_execution_request.v0"
    gate_id: ProductionLiveProviderGateId
    connector_id: str = Field(min_length=1)
    provider_name: str = Field(min_length=1)
    source_observation_path: str = Field(min_length=1)
    route_scope_ref: str = Field(min_length=1)
    connector_health_invocation_sha256: str = Field(min_length=1)
    connector_health_invocation_request_sha256: str = Field(min_length=1)
    connector_health_execution_ref: str = Field(min_length=1)
    connector_health_execution_sha256: str = Field(min_length=1)
    provider_dataset_ids: list[str] = Field(default_factory=list)
    reviewed_connector_health_effect_boundary_ref: str = Field(min_length=1)
    reviewed_connector_health_effect_boundary_sha256: str = Field(min_length=1)
    fallback_plan_ref: str = Field(min_length=1)
    fallback_plan_sha256: str = Field(min_length=1)
    credential_ref: str = Field(min_length=1)
    operator_identity_ref: str | None = None
    operator_identity_sha256: str | None = None
    operator_role: str | None = None
    idempotency_key: str = Field(min_length=1, max_length=128)
    runtime_ingest_performed_by_executor: bool = False
    safety_api_called: bool = False
    phase1_l0_l4_state_mutated: bool = False
    outbound_transport_invoked: bool = False
    hardware_control_performed: bool = False
    credential_material_embedded: bool = False
    raw_location_payload_embedded: bool = False
    raw_provider_payload_embedded: bool = False
    boundary: ProductionLiveConnectorHealthExecutionBoundary = Field(
        default_factory=ProductionLiveConnectorHealthExecutionBoundary
    )

    @model_validator(mode="after")
    def enforce_connector_health_execution_request(
        self,
    ) -> "ProductionLiveConnectorHealthExecutionRequest":
        _assert_production_live_source(
            "production_live_connector_health_executor",
            self.source_observation_path,
        )
        _assert_ref_prefix(
            "route_scope_ref",
            self.route_scope_ref,
            _PRODUCTION_LIVE_OBSERVATION_REF_PREFIXES,
        )
        _assert_ref_prefix(
            "connector_health_execution_ref",
            self.connector_health_execution_ref,
            _PRODUCTION_LIVE_OBSERVATION_REF_PREFIXES,
        )
        for field_name, value in (
            (
                "reviewed_connector_health_effect_boundary_ref",
                self.reviewed_connector_health_effect_boundary_ref,
            ),
            ("fallback_plan_ref", self.fallback_plan_ref),
            ("operator_identity_ref", self.operator_identity_ref),
        ):
            if value is not None:
                _assert_ref_prefix(
                    field_name,
                    value,
                    _PRODUCTION_LIVE_ATTESTATION_PREFIXES,
                )
        _assert_secret_ref(self.credential_ref)
        if (
            self.runtime_ingest_performed_by_executor
            or self.safety_api_called
            or self.phase1_l0_l4_state_mutated
            or self.outbound_transport_invoked
            or self.hardware_control_performed
        ):
            raise ValueError("connector health execution request cannot perform runtime effects")
        if self.credential_material_embedded:
            raise ValueError("connector health execution request cannot embed credentials")
        if self.raw_location_payload_embedded or self.raw_provider_payload_embedded:
            raise ValueError("connector health execution request cannot embed raw payloads")
        return self


class ProductionLiveConnectorHealthExecutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_production_live_connector_health_execution_result"
    artifact_version: str = "production_live_connector_health_execution_result.v0"
    source_provider: str = Field(min_length=1)
    source_path: str = Field(min_length=1)
    provider_dataset_ids: list[str] = Field(default_factory=list)
    health_status: ProductionLiveProviderHealthStatus = "unknown"
    connector_health_ref: str | None = None
    connector_health_sha256: str | None = None
    route_scoped_request_supported: bool = True
    freshness_attestation_supported: bool = True
    effect_boundary_required: bool = True
    executor_reported_connector_health_check_performed: bool = False
    executor_reported_provider_network_request_performed: bool = False
    executor_reported_real_provider_api_called: bool = False
    executor_reported_runtime_ingest_performed: bool = False
    executor_reported_safety_api_called: bool = False
    executor_reported_phase1_l0_l4_state_mutated: bool = False
    credential_material_embedded: bool = False
    raw_location_payload_embedded: bool = False
    raw_provider_payload_embedded: bool = False

    @model_validator(mode="after")
    def enforce_connector_health_execution_result(
        self,
    ) -> "ProductionLiveConnectorHealthExecutionResult":
        _assert_production_live_source(self.source_provider, self.source_path)
        if self.connector_health_ref is not None:
            _assert_ref_prefix(
                "connector_health_ref",
                self.connector_health_ref,
                _PRODUCTION_LIVE_ATTESTATION_PREFIXES,
            )
        if (
            self.executor_reported_runtime_ingest_performed
            or self.executor_reported_safety_api_called
            or self.executor_reported_phase1_l0_l4_state_mutated
        ):
            raise ValueError("connector health execution result cannot claim runtime effects")
        if self.credential_material_embedded:
            raise ValueError("connector health execution result cannot embed credentials")
        if self.raw_location_payload_embedded or self.raw_provider_payload_embedded:
            raise ValueError("connector health execution result cannot embed raw payloads")
        return self


class ProductionLiveConnectorHealthReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_production_live_connector_health_receipt"
    artifact_version: str = "production_live_connector_health_receipt.v0"
    source_provider: str = Field(min_length=1)
    source_path: str = Field(min_length=1)
    gate_id: ProductionLiveProviderGateId
    connector_id: str = Field(min_length=1)
    provider_name: str = Field(min_length=1)
    provider_dataset_ids: list[str] = Field(default_factory=list)
    route_scope_ref: str = Field(min_length=1)
    connector_health_invocation_sha256: str | None = None
    connector_health_execution_ref: str | None = None
    connector_health_execution_sha256: str | None = None
    health_status: ProductionLiveProviderHealthStatus = "unknown"
    connector_health_ref: str | None = None
    connector_health_sha256: str | None = None
    credential_ref: str | None = None
    freshness_requirement_minutes: int = Field(default=180, gt=0)
    route_scoped_request_supported: bool = True
    freshness_attestation_supported: bool = True
    effect_boundary_required: bool = True
    executor_reported_connector_health_check_performed: bool = False
    executor_reported_provider_network_request_performed: bool = False
    executor_reported_real_provider_api_called: bool = False
    executor_reported_runtime_ingest_performed: bool = False
    executor_reported_safety_api_called: bool = False
    executor_reported_phase1_l0_l4_state_mutated: bool = False
    credential_material_embedded: bool = False
    raw_location_payload_embedded: bool = False
    raw_provider_payload_embedded: bool = False

    @model_validator(mode="after")
    def enforce_connector_health_receipt(
        self,
    ) -> "ProductionLiveConnectorHealthReceipt":
        _assert_production_live_source(self.source_provider, self.source_path)
        _assert_ref_prefix(
            "route_scope_ref",
            self.route_scope_ref,
            _PRODUCTION_LIVE_OBSERVATION_REF_PREFIXES,
        )
        if self.connector_health_execution_ref is not None:
            _assert_ref_prefix(
                "connector_health_execution_ref",
                self.connector_health_execution_ref,
                _PRODUCTION_LIVE_OBSERVATION_REF_PREFIXES,
            )
        if (self.connector_health_execution_ref is None) != (
            self.connector_health_execution_sha256 is None
        ):
            raise ValueError("connector health execution ref and sha256 must be paired")
        if self.connector_health_ref is not None:
            _assert_ref_prefix(
                "connector_health_ref",
                self.connector_health_ref,
                _PRODUCTION_LIVE_ATTESTATION_PREFIXES,
            )
        if self.credential_ref is not None:
            _assert_secret_ref(self.credential_ref)
        if (
            self.executor_reported_runtime_ingest_performed
            or self.executor_reported_safety_api_called
            or self.executor_reported_phase1_l0_l4_state_mutated
        ):
            raise ValueError("connector health receipt cannot claim runtime effects")
        if self.credential_material_embedded:
            raise ValueError("connector health receipt cannot embed credentials")
        if self.raw_location_payload_embedded or self.raw_provider_payload_embedded:
            raise ValueError("connector health receipt cannot embed raw payloads")
        return self


class ProductionLiveConnectorHealthExecutionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_production_live_connector_health_execution_decision"
    artifact_version: str = "production_live_connector_health_execution_decision.v0"
    source_provider: str = "scout_runtime_safety_gate_adapters"
    source_path: str
    sha256: str
    status: ProductionLiveConnectorHealthExecutionStatus
    gate_id: ProductionLiveProviderGateId
    connector_id: str
    provider_name: str
    source_observation_path: str
    route_scope_ref: str
    connector_health_invocation_sha256: str
    connector_health_invocation_request_sha256: str
    connector_health_execution_ref: str | None = None
    connector_health_execution_sha256: str | None = None
    execution_request_sha256: str | None = None
    health_receipt_sha256: str | None = None
    health_receipt: ProductionLiveConnectorHealthReceipt | None = None
    connector_health_invocation_authorized: bool = False
    connector_health_client_called: bool = False
    connector_health_client_result_valid: bool = False
    connector_health_client_effect_present: bool = False
    runtime_ingest_performed_by_executor: bool = False
    safety_api_called: bool = False
    phase1_l0_l4_state_mutated: bool = False
    outbound_transport_invoked: bool = False
    hardware_control_performed: bool = False
    blockers: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    boundary: ProductionLiveConnectorHealthExecutionBoundary = Field(
        default_factory=ProductionLiveConnectorHealthExecutionBoundary
    )

    @model_validator(mode="after")
    def enforce_connector_health_execution_decision(
        self,
    ) -> "ProductionLiveConnectorHealthExecutionDecision":
        emitted = self.status == "connector_health_receipt_emitted"
        if emitted and not (
            self.health_receipt
            and self.health_receipt_sha256
            and self.execution_request_sha256
            and self.connector_health_invocation_authorized
            and self.connector_health_client_called
            and self.connector_health_client_result_valid
            and self.connector_health_client_effect_present
        ):
            raise ValueError("emitted connector health receipt requires all gates")
        if not emitted and (self.health_receipt or self.health_receipt_sha256):
            raise ValueError("blocked connector health execution cannot include receipt")
        if (
            self.runtime_ingest_performed_by_executor
            or self.safety_api_called
            or self.phase1_l0_l4_state_mutated
            or self.outbound_transport_invoked
            or self.hardware_control_performed
        ):
            raise ValueError("connector health execution decision cannot perform runtime effects")
        return self


class ProductionLiveConnectorHealthIntakeDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_production_live_connector_health_intake"
    artifact_version: str = "production_live_connector_health_intake.v0"
    source_provider: str = "scout_runtime_safety_gate_adapters"
    source_path: str
    sha256: str
    status: ProductionLiveConnectorHealthIntakeStatus
    gate_id: ProductionLiveProviderGateId
    connector_id: str
    health_receipt_sha256: str
    connector_manifest_sha256: str | None = None
    source_observation_path: str
    route_scope_ref: str
    connector_health_invocation_sha256: str | None = None
    connector_health_execution_ref: str | None = None
    connector_health_execution_sha256: str | None = None
    health_status: ProductionLiveProviderHealthStatus
    connector_health_ref: str | None = None
    connector_health_sha256: str | None = None
    credential_ref_present: bool = False
    connector_health_invocation_authorized: bool = False
    connector_health_invocation_lineage_match: bool = False
    connector_health_check_performed: bool = False
    connector_health_evidence_present: bool = False
    connector_healthy: bool = False
    connector_manifest_prepared: bool = False
    connector_manifest: ProductionLiveProviderConnectorManifest | None = None
    executor_reported_provider_network_request_performed: bool = False
    executor_reported_real_provider_api_called: bool = False
    connector_health_checked_by_intake: bool = False
    provider_network_request_performed_by_intake: bool = False
    real_provider_api_called_by_intake: bool = False
    runtime_ingest_performed_by_intake: bool = False
    safety_api_called: bool = False
    phase1_l0_l4_state_mutated: bool = False
    blockers: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    boundary: ProductionLiveConnectorHealthIntakeBoundary = Field(
        default_factory=ProductionLiveConnectorHealthIntakeBoundary
    )

    @model_validator(mode="after")
    def enforce_connector_health_intake(
        self,
    ) -> "ProductionLiveConnectorHealthIntakeDecision":
        prepared = self.status == "connector_manifest_prepared"
        if self.connector_manifest_prepared != prepared:
            raise ValueError("connector_manifest_prepared must match status")
        if prepared and not (self.connector_manifest and self.connector_manifest_sha256):
            raise ValueError("prepared connector health intake requires manifest")
        if not prepared and (self.connector_manifest or self.connector_manifest_sha256):
            raise ValueError("blocked connector health intake cannot include manifest")
        if (
            self.connector_health_checked_by_intake
            or self.provider_network_request_performed_by_intake
            or self.real_provider_api_called_by_intake
            or self.runtime_ingest_performed_by_intake
            or self.safety_api_called
            or self.phase1_l0_l4_state_mutated
        ):
            raise ValueError("connector health intake cannot perform effects")
        return self


class ProductionLiveFieldDeviceValidatorInvocationBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deterministic_invocation_guard_only: bool = True
    field_device_validation_performed_by_guard: bool = False
    provider_network_request_performed_by_guard: bool = False
    real_provider_api_called_by_guard: bool = False
    runtime_ingest_performed_by_guard: bool = False
    safety_api_called: bool = False
    phase1_l0_l4_state_mutated: bool = False
    credential_material_embedded: bool = False
    raw_location_payload_embedded: bool = False
    raw_provider_payload_embedded: bool = False

    @model_validator(mode="after")
    def enforce_field_device_validator_invocation_boundary(
        self,
    ) -> "ProductionLiveFieldDeviceValidatorInvocationBoundary":
        if not self.deterministic_invocation_guard_only:
            raise ValueError("field/device validator invocation guard must be deterministic")
        if (
            self.field_device_validation_performed_by_guard
            or self.provider_network_request_performed_by_guard
            or self.real_provider_api_called_by_guard
            or self.runtime_ingest_performed_by_guard
            or self.safety_api_called
            or self.phase1_l0_l4_state_mutated
        ):
            raise ValueError(
                "field/device validator invocation guard cannot perform effects"
            )
        if self.credential_material_embedded:
            raise ValueError(
                "field/device validator invocation guard cannot embed credentials"
            )
        if self.raw_location_payload_embedded or self.raw_provider_payload_embedded:
            raise ValueError(
                "field/device validator invocation guard cannot embed raw payloads"
            )
        return self


class ProductionLiveFieldDeviceValidatorInvocationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_production_live_field_device_validator_invocation_request"
    artifact_version: str = "production_live_field_device_validator_invocation_request.v0"
    source_provider: str = Field(min_length=1)
    source_path: str = Field(min_length=1)
    gate_id: ProductionLiveProviderGateId
    source_observation_path: str | None = None
    route_scope_ref: str = Field(min_length=1)
    provider_request_ref: str | None = None
    provider_response_receipt_sha256: str | None = None
    current_observation_ref: str | None = None
    device_evidence_ref: str | None = None
    device_evidence_sha256: str | None = None
    reviewed_field_device_validator_effect_boundary_ref: str | None = None
    reviewed_field_device_validator_effect_boundary_sha256: str | None = None
    fallback_plan_ref: str | None = None
    fallback_plan_sha256: str | None = None
    operator_identity_ref: str | None = None
    operator_identity_sha256: str | None = None
    operator_role: str | None = None
    explicit_confirmation: bool = False
    confirmation_phrase: str | None = None
    idempotency_key: str = Field(min_length=1, max_length=128)
    field_device_validation_performed_by_guard: bool = False
    provider_network_request_performed_by_guard: bool = False
    real_provider_api_called_by_guard: bool = False
    runtime_ingest_performed_by_guard: bool = False
    safety_api_called: bool = False
    phase1_l0_l4_state_mutated: bool = False
    credential_material_embedded: bool = False
    raw_location_payload_embedded: bool = False
    raw_provider_payload_embedded: bool = False

    @model_validator(mode="after")
    def enforce_field_device_validator_invocation_request(
        self,
    ) -> "ProductionLiveFieldDeviceValidatorInvocationRequest":
        _assert_ref_prefix(
            "source_path",
            self.source_path,
            _PRODUCTION_LIVE_ATTESTATION_PREFIXES,
        )
        if self.source_observation_path is not None:
            _assert_production_live_source(
                self.source_provider,
                self.source_observation_path,
            )
        _assert_ref_prefix(
            "route_scope_ref",
            self.route_scope_ref,
            _PRODUCTION_LIVE_OBSERVATION_REF_PREFIXES,
        )
        for field_name, value, prefixes in (
            (
                "provider_request_ref",
                self.provider_request_ref,
                _PRODUCTION_LIVE_OBSERVATION_REF_PREFIXES,
            ),
            (
                "current_observation_ref",
                self.current_observation_ref,
                _PRODUCTION_LIVE_OBSERVATION_REF_PREFIXES,
            ),
            (
                "device_evidence_ref",
                self.device_evidence_ref,
                _PRODUCTION_LIVE_OBSERVATION_REF_PREFIXES,
            ),
            (
                "reviewed_field_device_validator_effect_boundary_ref",
                self.reviewed_field_device_validator_effect_boundary_ref,
                _PRODUCTION_LIVE_ATTESTATION_PREFIXES,
            ),
            ("fallback_plan_ref", self.fallback_plan_ref, _PRODUCTION_LIVE_ATTESTATION_PREFIXES),
            (
                "operator_identity_ref",
                self.operator_identity_ref,
                _PRODUCTION_LIVE_ATTESTATION_PREFIXES,
            ),
        ):
            if value is not None:
                _assert_ref_prefix(field_name, value, prefixes)
        for ref_name, ref_value, sha_name, sha_value in (
            (
                "device_evidence_ref",
                self.device_evidence_ref,
                "device_evidence_sha256",
                self.device_evidence_sha256,
            ),
            (
                "reviewed_field_device_validator_effect_boundary_ref",
                self.reviewed_field_device_validator_effect_boundary_ref,
                "reviewed_field_device_validator_effect_boundary_sha256",
                self.reviewed_field_device_validator_effect_boundary_sha256,
            ),
            (
                "fallback_plan_ref",
                self.fallback_plan_ref,
                "fallback_plan_sha256",
                self.fallback_plan_sha256,
            ),
            (
                "operator_identity_ref",
                self.operator_identity_ref,
                "operator_identity_sha256",
                self.operator_identity_sha256,
            ),
        ):
            if (ref_value is None) != (sha_value is None):
                raise ValueError(f"{ref_name} and {sha_name} must be paired")
        if (
            self.field_device_validation_performed_by_guard
            or self.provider_network_request_performed_by_guard
            or self.real_provider_api_called_by_guard
            or self.runtime_ingest_performed_by_guard
            or self.safety_api_called
            or self.phase1_l0_l4_state_mutated
        ):
            raise ValueError(
                "field/device validator invocation request cannot perform effects"
            )
        if self.credential_material_embedded:
            raise ValueError(
                "field/device validator invocation request cannot embed credentials"
            )
        if self.raw_location_payload_embedded or self.raw_provider_payload_embedded:
            raise ValueError(
                "field/device validator invocation request cannot embed raw payloads"
            )
        return self


class ProductionLiveFieldDeviceValidatorInvocationReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_production_live_field_device_validator_invocation_receipt"
    artifact_version: str = "production_live_field_device_validator_invocation_receipt.v0"
    source_provider: str = "scout_runtime_safety_gate_adapters"
    source_path: str
    sha256: str
    status: ProductionLiveFieldDeviceValidatorInvocationStatus
    gate_id: ProductionLiveProviderGateId
    field_device_validator_invocation_request_sha256: str
    source_observation_path: str | None = None
    route_scope_ref: str
    provider_request_ref: str | None = None
    provider_response_receipt_sha256: str | None = None
    current_observation_ref: str | None = None
    device_evidence_ref: str | None = None
    device_evidence_sha256: str | None = None
    reviewed_field_device_validator_effect_boundary_ref: str | None = None
    reviewed_field_device_validator_effect_boundary_sha256: str | None = None
    fallback_plan_ref: str | None = None
    fallback_plan_sha256: str | None = None
    operator_identity_ref: str | None = None
    operator_identity_sha256: str | None = None
    operator_role: str | None = None
    idempotency_key: str
    field_device_validation_execution_ref: str | None = None
    field_device_validation_execution_sha256: str | None = None
    field_device_validator_effect_boundary_present: bool = False
    field_device_validator_input_evidence_present: bool = False
    fallback_plan_present: bool = False
    operator_identity_present: bool = False
    explicit_confirmation_present: bool = False
    field_device_validator_invocation_authorized: bool = False
    field_device_validation_performed_by_guard: bool = False
    provider_network_request_performed_by_guard: bool = False
    real_provider_api_called_by_guard: bool = False
    runtime_ingest_performed_by_guard: bool = False
    safety_api_called: bool = False
    phase1_l0_l4_state_mutated: bool = False
    credential_material_embedded: bool = False
    raw_location_payload_embedded: bool = False
    raw_provider_payload_embedded: bool = False
    blockers: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    boundary: ProductionLiveFieldDeviceValidatorInvocationBoundary = Field(
        default_factory=ProductionLiveFieldDeviceValidatorInvocationBoundary
    )

    @model_validator(mode="after")
    def enforce_field_device_validator_invocation_receipt(
        self,
    ) -> "ProductionLiveFieldDeviceValidatorInvocationReceipt":
        authorized = self.status == "field_device_validator_invocation_authorized"
        if self.field_device_validator_invocation_authorized != authorized:
            raise ValueError("field/device validator authorization must match status")
        if authorized and not (
            self.field_device_validator_effect_boundary_present
            and self.field_device_validator_input_evidence_present
            and self.fallback_plan_present
            and self.operator_identity_present
            and self.explicit_confirmation_present
            and self.field_device_validation_execution_ref
            and self.field_device_validation_execution_sha256
        ):
            raise ValueError("authorized field/device validator invocation requires all gates")
        if (self.field_device_validation_execution_ref is None) != (
            self.field_device_validation_execution_sha256 is None
        ):
            raise ValueError("field/device validation execution ref and sha256 must be paired")
        if self.field_device_validation_execution_ref is not None:
            _assert_ref_prefix(
                "field_device_validation_execution_ref",
                self.field_device_validation_execution_ref,
                _PRODUCTION_LIVE_ATTESTATION_PREFIXES,
            )
        if (
            self.field_device_validation_performed_by_guard
            or self.provider_network_request_performed_by_guard
            or self.real_provider_api_called_by_guard
            or self.runtime_ingest_performed_by_guard
            or self.safety_api_called
            or self.phase1_l0_l4_state_mutated
        ):
            raise ValueError(
                "field/device validator invocation receipt cannot perform effects"
            )
        if self.credential_material_embedded:
            raise ValueError(
                "field/device validator invocation receipt cannot embed credentials"
            )
        if self.raw_location_payload_embedded or self.raw_provider_payload_embedded:
            raise ValueError(
                "field/device validator invocation receipt cannot embed raw payloads"
            )
        return self


class ProductionLiveFieldDeviceValidationBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deterministic_intake_only: bool = True
    field_device_validation_performed_by_intake: bool = False
    provider_network_request_performed_by_intake: bool = False
    real_provider_api_called_by_intake: bool = False
    runtime_ingest_performed_by_intake: bool = False
    safety_api_called: bool = False
    phase1_l0_l4_state_mutated: bool = False
    credential_material_embedded: bool = False
    raw_location_payload_embedded: bool = False
    raw_provider_payload_embedded: bool = False

    @model_validator(mode="after")
    def enforce_field_device_validation_boundary(
        self,
    ) -> "ProductionLiveFieldDeviceValidationBoundary":
        if not self.deterministic_intake_only:
            raise ValueError("field/device validation intake must be deterministic")
        if (
            self.field_device_validation_performed_by_intake
            or self.provider_network_request_performed_by_intake
            or self.real_provider_api_called_by_intake
            or self.runtime_ingest_performed_by_intake
            or self.safety_api_called
            or self.phase1_l0_l4_state_mutated
        ):
            raise ValueError("field/device validation intake cannot perform effects")
        if self.credential_material_embedded:
            raise ValueError("field/device validation intake cannot embed credentials")
        if self.raw_location_payload_embedded or self.raw_provider_payload_embedded:
            raise ValueError("field/device validation intake cannot embed raw payloads")
        return self


class ProductionLiveFieldDeviceValidationReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_production_live_field_device_validation_receipt"
    artifact_version: str = "production_live_field_device_validation_receipt.v0"
    source_provider: str = Field(min_length=1)
    source_path: str = Field(min_length=1)
    gate_id: ProductionLiveProviderGateId
    source_observation_path: str | None = None
    route_scope_ref: str = Field(min_length=1)
    provider_request_ref: str | None = None
    provider_response_receipt_sha256: str | None = None
    field_device_validator_invocation_sha256: str | None = None
    field_device_validation_execution_ref: str | None = None
    field_device_validation_execution_sha256: str | None = None
    current_observation_ref: str | None = None
    field_attestation_ref: str | None = None
    field_attestation_sha256: str | None = None
    device_evidence_ref: str | None = None
    device_evidence_sha256: str | None = None
    operator_review_ref: str | None = None
    operator_review_sha256: str | None = None
    validation_status: ProductionLiveFieldDeviceValidationStatus = "unknown"
    validation_age_minutes: float = Field(ge=0)
    max_validation_age_minutes: int = Field(default=180, gt=0)
    route_context: SafetyGateRouteContext = Field(default_factory=SafetyGateRouteContext)
    confidence: SafetyGateConfidence = "medium"
    executor_reported_field_device_validation_performed: bool = False
    executor_reported_provider_network_request_performed: bool = False
    executor_reported_real_provider_api_called: bool = False
    executor_reported_runtime_ingest_performed: bool = False
    executor_reported_safety_api_called: bool = False
    executor_reported_phase1_l0_l4_state_mutated: bool = False
    credential_material_embedded: bool = False
    raw_location_payload_embedded: bool = False
    raw_provider_payload_embedded: bool = False

    @model_validator(mode="after")
    def enforce_field_device_validation_receipt(
        self,
    ) -> "ProductionLiveFieldDeviceValidationReceipt":
        _assert_ref_prefix(
            "source_path",
            self.source_path,
            _PRODUCTION_LIVE_OBSERVATION_REF_PREFIXES,
        )
        if self.source_observation_path is not None:
            _assert_production_live_source(
                self.source_provider,
                self.source_observation_path,
            )
        _assert_ref_prefix(
            "route_scope_ref",
            self.route_scope_ref,
            _PRODUCTION_LIVE_OBSERVATION_REF_PREFIXES,
        )
        if self.provider_request_ref is not None:
            _assert_ref_prefix(
                "provider_request_ref",
                self.provider_request_ref,
                _PRODUCTION_LIVE_OBSERVATION_REF_PREFIXES,
            )
        if (self.field_device_validation_execution_ref is None) != (
            self.field_device_validation_execution_sha256 is None
        ):
            raise ValueError("field/device validation execution ref and sha256 must be paired")
        if self.field_device_validation_execution_ref is not None:
            _assert_ref_prefix(
                "field_device_validation_execution_ref",
                self.field_device_validation_execution_ref,
                _PRODUCTION_LIVE_ATTESTATION_PREFIXES,
            )
        if self.current_observation_ref is not None:
            _assert_ref_prefix(
                "current_observation_ref",
                self.current_observation_ref,
                _PRODUCTION_LIVE_OBSERVATION_REF_PREFIXES,
            )
        if self.field_attestation_ref is not None:
            _assert_ref_prefix(
                "field_attestation_ref",
                self.field_attestation_ref,
                _PRODUCTION_LIVE_ATTESTATION_PREFIXES,
            )
        if self.device_evidence_ref is not None:
            _assert_ref_prefix(
                "device_evidence_ref",
                self.device_evidence_ref,
                _PRODUCTION_LIVE_OBSERVATION_REF_PREFIXES,
            )
        if self.operator_review_ref is not None:
            _assert_ref_prefix(
                "operator_review_ref",
                self.operator_review_ref,
                _PRODUCTION_LIVE_ATTESTATION_PREFIXES,
            )
        _assert_route_scope(self.route_context)
        if (
            self.executor_reported_runtime_ingest_performed
            or self.executor_reported_safety_api_called
            or self.executor_reported_phase1_l0_l4_state_mutated
        ):
            raise ValueError("field/device validation receipt cannot claim runtime effects")
        if self.credential_material_embedded:
            raise ValueError("field/device validation receipt cannot embed credentials")
        if self.raw_location_payload_embedded or self.raw_provider_payload_embedded:
            raise ValueError("field/device validation receipt cannot embed raw payloads")
        return self


class ProductionLiveFieldDeviceValidationDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_production_live_field_device_validation_intake"
    artifact_version: str = "production_live_field_device_validation_intake.v0"
    source_provider: str = "scout_runtime_safety_gate_adapters"
    source_path: str
    sha256: str
    status: ProductionLiveFieldDeviceValidationIntakeStatus
    gate_id: ProductionLiveProviderGateId
    validation_receipt_sha256: str
    provider_response_receipt_sha256: str | None = None
    source_observation_path: str | None = None
    route_scope_ref: str
    provider_request_ref: str | None = None
    field_device_validator_invocation_sha256: str | None = None
    field_device_validation_execution_ref: str | None = None
    field_device_validation_execution_sha256: str | None = None
    current_observation_ref: str | None = None
    field_attestation_ref: str | None = None
    field_attestation_sha256: str | None = None
    device_evidence_ref: str | None = None
    device_evidence_sha256: str | None = None
    operator_review_ref: str | None = None
    operator_review_sha256: str | None = None
    validation_status: ProductionLiveFieldDeviceValidationStatus
    validation_age_minutes: float = Field(ge=0)
    max_validation_age_minutes: int = Field(gt=0)
    field_device_validation_performed: bool = False
    field_device_validation_evidence_present: bool = False
    field_device_validation_confirmed: bool = False
    field_device_validation_current: bool = False
    field_device_validation_prepared: bool = False
    field_device_validator_invocation_authorized: bool = False
    field_device_validator_invocation_lineage_match: bool = False
    field_device_validation_performed_by_intake: bool = False
    provider_network_request_performed_by_intake: bool = False
    real_provider_api_called_by_intake: bool = False
    runtime_ingest_performed_by_intake: bool = False
    safety_api_called: bool = False
    phase1_l0_l4_state_mutated: bool = False
    blockers: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    boundary: ProductionLiveFieldDeviceValidationBoundary = Field(
        default_factory=ProductionLiveFieldDeviceValidationBoundary
    )

    @model_validator(mode="after")
    def enforce_field_device_validation_decision(
        self,
    ) -> "ProductionLiveFieldDeviceValidationDecision":
        prepared = self.status == "field_device_validation_prepared"
        if self.field_device_validation_prepared != prepared:
            raise ValueError("field_device_validation_prepared must match status")
        if prepared and not (
            self.field_device_validation_performed
            and self.field_device_validation_evidence_present
            and self.field_device_validation_confirmed
            and self.field_device_validation_current
            and self.field_attestation_ref
            and self.field_attestation_sha256
            and (
                self.current_observation_ref
                or (self.device_evidence_ref and self.device_evidence_sha256)
            )
        ):
            raise ValueError("prepared field/device validation requires all checks")
        if (
            self.field_device_validation_performed_by_intake
            or self.provider_network_request_performed_by_intake
            or self.real_provider_api_called_by_intake
            or self.runtime_ingest_performed_by_intake
            or self.safety_api_called
            or self.phase1_l0_l4_state_mutated
        ):
            raise ValueError("field/device validation intake cannot perform effects")
        return self


class ProductionLiveFieldDeviceValidationExecutionBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reviewed_field_device_validator_effect_boundary_required: bool = True
    injected_field_device_validation_client_required: bool = True
    field_device_validation_allowed: bool = True
    provider_network_request_performed_by_executor: bool = False
    real_provider_api_called_by_executor: bool = False
    runtime_ingest_performed_by_executor: bool = False
    safety_api_called: bool = False
    phase1_l0_l4_state_mutated: bool = False
    outbound_transport_invoked: bool = False
    hardware_control_performed: bool = False
    credential_material_embedded: bool = False
    raw_location_payload_embedded: bool = False
    raw_provider_payload_embedded: bool = False

    @model_validator(mode="after")
    def enforce_field_device_validation_execution_boundary(
        self,
    ) -> "ProductionLiveFieldDeviceValidationExecutionBoundary":
        if not self.reviewed_field_device_validator_effect_boundary_required:
            raise ValueError("field/device executor requires a reviewed boundary")
        if not self.injected_field_device_validation_client_required:
            raise ValueError("field/device executor requires an injected client")
        if not self.field_device_validation_allowed:
            raise ValueError("field/device executor must allow field validation")
        if (
            self.provider_network_request_performed_by_executor
            or self.real_provider_api_called_by_executor
            or self.runtime_ingest_performed_by_executor
            or self.safety_api_called
            or self.phase1_l0_l4_state_mutated
            or self.outbound_transport_invoked
            or self.hardware_control_performed
        ):
            raise ValueError("field/device executor boundary cannot perform runtime effects")
        if self.credential_material_embedded:
            raise ValueError("field/device executor boundary cannot embed credentials")
        if self.raw_location_payload_embedded or self.raw_provider_payload_embedded:
            raise ValueError("field/device executor boundary cannot embed raw payloads")
        return self


class ProductionLiveFieldDeviceValidationExecutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_production_live_field_device_validation_execution_request"
    artifact_version: str = "production_live_field_device_validation_execution_request.v0"
    gate_id: ProductionLiveProviderGateId
    field_device_validator_invocation_sha256: str = Field(min_length=1)
    field_device_validator_invocation_request_sha256: str = Field(min_length=1)
    source_observation_path: str | None = None
    route_scope_ref: str = Field(min_length=1)
    provider_request_ref: str | None = None
    provider_response_receipt_sha256: str | None = None
    current_observation_ref: str | None = None
    device_evidence_ref: str | None = None
    device_evidence_sha256: str | None = None
    field_device_validation_execution_ref: str = Field(min_length=1)
    field_device_validation_execution_sha256: str = Field(min_length=1)
    reviewed_field_device_validator_effect_boundary_ref: str = Field(min_length=1)
    reviewed_field_device_validator_effect_boundary_sha256: str = Field(min_length=1)
    fallback_plan_ref: str = Field(min_length=1)
    fallback_plan_sha256: str = Field(min_length=1)
    operator_identity_ref: str | None = None
    operator_identity_sha256: str | None = None
    operator_role: str | None = None
    idempotency_key: str = Field(min_length=1, max_length=128)
    provider_network_request_performed_by_executor: bool = False
    real_provider_api_called_by_executor: bool = False
    runtime_ingest_performed_by_executor: bool = False
    safety_api_called: bool = False
    phase1_l0_l4_state_mutated: bool = False
    outbound_transport_invoked: bool = False
    hardware_control_performed: bool = False
    credential_material_embedded: bool = False
    raw_location_payload_embedded: bool = False
    raw_provider_payload_embedded: bool = False
    boundary: ProductionLiveFieldDeviceValidationExecutionBoundary = Field(
        default_factory=ProductionLiveFieldDeviceValidationExecutionBoundary
    )

    @model_validator(mode="after")
    def enforce_field_device_validation_execution_request(
        self,
    ) -> "ProductionLiveFieldDeviceValidationExecutionRequest":
        if self.source_observation_path is not None:
            _assert_ref_prefix(
                "source_observation_path",
                self.source_observation_path,
                _PRODUCTION_LIVE_OBSERVATION_REF_PREFIXES,
            )
        _assert_ref_prefix(
            "route_scope_ref",
            self.route_scope_ref,
            _PRODUCTION_LIVE_OBSERVATION_REF_PREFIXES,
        )
        for field_name, value, prefixes in (
            (
                "provider_request_ref",
                self.provider_request_ref,
                _PRODUCTION_LIVE_OBSERVATION_REF_PREFIXES,
            ),
            (
                "current_observation_ref",
                self.current_observation_ref,
                _PRODUCTION_LIVE_OBSERVATION_REF_PREFIXES,
            ),
            (
                "device_evidence_ref",
                self.device_evidence_ref,
                _PRODUCTION_LIVE_OBSERVATION_REF_PREFIXES,
            ),
            (
                "field_device_validation_execution_ref",
                self.field_device_validation_execution_ref,
                _PRODUCTION_LIVE_ATTESTATION_PREFIXES,
            ),
            (
                "reviewed_field_device_validator_effect_boundary_ref",
                self.reviewed_field_device_validator_effect_boundary_ref,
                _PRODUCTION_LIVE_ATTESTATION_PREFIXES,
            ),
            (
                "fallback_plan_ref",
                self.fallback_plan_ref,
                _PRODUCTION_LIVE_ATTESTATION_PREFIXES,
            ),
            (
                "operator_identity_ref",
                self.operator_identity_ref,
                _PRODUCTION_LIVE_ATTESTATION_PREFIXES,
            ),
        ):
            if value is not None:
                _assert_ref_prefix(field_name, value, prefixes)
        if (
            self.provider_network_request_performed_by_executor
            or self.real_provider_api_called_by_executor
            or self.runtime_ingest_performed_by_executor
            or self.safety_api_called
            or self.phase1_l0_l4_state_mutated
            or self.outbound_transport_invoked
            or self.hardware_control_performed
        ):
            raise ValueError("field/device execution request cannot perform runtime effects")
        if self.credential_material_embedded:
            raise ValueError("field/device execution request cannot embed credentials")
        if self.raw_location_payload_embedded or self.raw_provider_payload_embedded:
            raise ValueError("field/device execution request cannot embed raw payloads")
        return self


class ProductionLiveFieldDeviceValidationExecutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_production_live_field_device_validation_execution_result"
    artifact_version: str = "production_live_field_device_validation_execution_result.v0"
    source_provider: str = Field(min_length=1)
    source_path: str = Field(min_length=1)
    gate_id: ProductionLiveProviderGateId
    source_observation_path: str | None = None
    route_scope_ref: str = Field(min_length=1)
    provider_request_ref: str | None = None
    provider_response_receipt_sha256: str | None = None
    current_observation_ref: str | None = None
    field_attestation_ref: str | None = None
    field_attestation_sha256: str | None = None
    device_evidence_ref: str | None = None
    device_evidence_sha256: str | None = None
    operator_review_ref: str | None = None
    operator_review_sha256: str | None = None
    validation_status: ProductionLiveFieldDeviceValidationStatus = "unknown"
    validation_age_minutes: float = Field(ge=0)
    max_validation_age_minutes: int = Field(default=180, gt=0)
    route_context: SafetyGateRouteContext = Field(default_factory=SafetyGateRouteContext)
    confidence: SafetyGateConfidence = "medium"
    executor_reported_field_device_validation_performed: bool = False
    executor_reported_provider_network_request_performed: bool = False
    executor_reported_real_provider_api_called: bool = False
    executor_reported_runtime_ingest_performed: bool = False
    executor_reported_safety_api_called: bool = False
    executor_reported_phase1_l0_l4_state_mutated: bool = False
    credential_material_embedded: bool = False
    raw_location_payload_embedded: bool = False
    raw_provider_payload_embedded: bool = False

    @model_validator(mode="after")
    def enforce_field_device_validation_execution_result(
        self,
    ) -> "ProductionLiveFieldDeviceValidationExecutionResult":
        _assert_ref_prefix(
            "source_path",
            self.source_path,
            _PRODUCTION_LIVE_OBSERVATION_REF_PREFIXES,
        )
        if self.source_observation_path is not None:
            _assert_ref_prefix(
                "source_observation_path",
                self.source_observation_path,
                _PRODUCTION_LIVE_OBSERVATION_REF_PREFIXES,
            )
        _assert_ref_prefix(
            "route_scope_ref",
            self.route_scope_ref,
            _PRODUCTION_LIVE_OBSERVATION_REF_PREFIXES,
        )
        for field_name, value, prefixes in (
            (
                "provider_request_ref",
                self.provider_request_ref,
                _PRODUCTION_LIVE_OBSERVATION_REF_PREFIXES,
            ),
            (
                "current_observation_ref",
                self.current_observation_ref,
                _PRODUCTION_LIVE_OBSERVATION_REF_PREFIXES,
            ),
            (
                "field_attestation_ref",
                self.field_attestation_ref,
                _PRODUCTION_LIVE_ATTESTATION_PREFIXES,
            ),
            (
                "device_evidence_ref",
                self.device_evidence_ref,
                _PRODUCTION_LIVE_OBSERVATION_REF_PREFIXES,
            ),
            (
                "operator_review_ref",
                self.operator_review_ref,
                _PRODUCTION_LIVE_ATTESTATION_PREFIXES,
            ),
        ):
            if value is not None:
                _assert_ref_prefix(field_name, value, prefixes)
        _assert_route_scope(self.route_context)
        if (
            self.executor_reported_provider_network_request_performed
            or self.executor_reported_real_provider_api_called
            or self.executor_reported_runtime_ingest_performed
            or self.executor_reported_safety_api_called
            or self.executor_reported_phase1_l0_l4_state_mutated
        ):
            raise ValueError("field/device execution result cannot claim runtime effects")
        if self.credential_material_embedded:
            raise ValueError("field/device execution result cannot embed credentials")
        if self.raw_location_payload_embedded or self.raw_provider_payload_embedded:
            raise ValueError("field/device execution result cannot embed raw payloads")
        return self


class ProductionLiveFieldDeviceValidationExecutionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_production_live_field_device_validation_execution_decision"
    artifact_version: str = "production_live_field_device_validation_execution_decision.v0"
    source_provider: str = "scout_runtime_safety_gate_adapters"
    source_path: str
    sha256: str
    status: ProductionLiveFieldDeviceValidationExecutionStatus
    gate_id: ProductionLiveProviderGateId
    field_device_validator_invocation_sha256: str
    field_device_validation_execution_ref: str | None = None
    field_device_validation_execution_sha256: str | None = None
    execution_request_sha256: str | None = None
    validation_receipt_sha256: str | None = None
    validation_receipt: ProductionLiveFieldDeviceValidationReceipt | None = None
    field_device_validator_invocation_authorized: bool = False
    field_device_validation_client_called: bool = False
    field_device_validation_client_result_valid: bool = False
    field_device_validation_client_effect_present: bool = False
    provider_network_request_performed_by_executor: bool = False
    real_provider_api_called_by_executor: bool = False
    runtime_ingest_performed_by_executor: bool = False
    safety_api_called: bool = False
    phase1_l0_l4_state_mutated: bool = False
    outbound_transport_invoked: bool = False
    hardware_control_performed: bool = False
    blockers: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    boundary: ProductionLiveFieldDeviceValidationExecutionBoundary = Field(
        default_factory=ProductionLiveFieldDeviceValidationExecutionBoundary
    )

    @model_validator(mode="after")
    def enforce_field_device_validation_execution_decision(
        self,
    ) -> "ProductionLiveFieldDeviceValidationExecutionDecision":
        emitted = self.status == "field_device_validation_receipt_emitted"
        if emitted and not (
            self.validation_receipt
            and self.validation_receipt_sha256
            and self.execution_request_sha256
            and self.field_device_validator_invocation_authorized
            and self.field_device_validation_client_called
            and self.field_device_validation_client_result_valid
            and self.field_device_validation_client_effect_present
        ):
            raise ValueError("emitted field/device validation receipt requires all gates")
        if not emitted and (self.validation_receipt or self.validation_receipt_sha256):
            raise ValueError("blocked field/device execution cannot include receipt")
        if (
            self.provider_network_request_performed_by_executor
            or self.real_provider_api_called_by_executor
            or self.runtime_ingest_performed_by_executor
            or self.safety_api_called
            or self.phase1_l0_l4_state_mutated
            or self.outbound_transport_invoked
            or self.hardware_control_performed
        ):
            raise ValueError("field/device execution decision cannot perform runtime effects")
        return self


class ProductionLiveFreshnessAttestorInvocationBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deterministic_invocation_guard_only: bool = True
    freshness_check_performed_by_guard: bool = False
    connector_health_checked_by_guard: bool = False
    provider_network_request_performed_by_guard: bool = False
    real_provider_api_called_by_guard: bool = False
    runtime_ingest_performed_by_guard: bool = False
    safety_api_called: bool = False
    phase1_l0_l4_state_mutated: bool = False
    credential_material_embedded: bool = False
    raw_location_payload_embedded: bool = False
    raw_provider_payload_embedded: bool = False

    @model_validator(mode="after")
    def enforce_freshness_attestor_invocation_boundary(
        self,
    ) -> "ProductionLiveFreshnessAttestorInvocationBoundary":
        if not self.deterministic_invocation_guard_only:
            raise ValueError("freshness attestor invocation guard must be deterministic")
        if (
            self.freshness_check_performed_by_guard
            or self.connector_health_checked_by_guard
            or self.provider_network_request_performed_by_guard
            or self.real_provider_api_called_by_guard
            or self.runtime_ingest_performed_by_guard
            or self.safety_api_called
            or self.phase1_l0_l4_state_mutated
        ):
            raise ValueError("freshness attestor invocation guard cannot perform effects")
        if self.credential_material_embedded:
            raise ValueError("freshness attestor invocation guard cannot embed credentials")
        if self.raw_location_payload_embedded or self.raw_provider_payload_embedded:
            raise ValueError("freshness attestor invocation guard cannot embed raw payloads")
        return self


class ProductionLiveFreshnessAttestorInvocationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_production_live_freshness_attestor_invocation_request"
    artifact_version: str = "production_live_freshness_attestor_invocation_request.v0"
    source_provider: str = Field(min_length=1)
    source_path: str = Field(min_length=1)
    gate_id: ProductionLiveProviderGateId
    source_observation_path: str | None = None
    route_scope_ref: str = Field(min_length=1)
    provider_request_ref: str | None = None
    provider_response_receipt_sha256: str | None = None
    provider_evidence_ref: str | None = None
    provider_evidence_sha256: str | None = None
    freshness_requirement_minutes: int = Field(default=180, gt=0)
    reviewed_freshness_attestor_effect_boundary_ref: str | None = None
    reviewed_freshness_attestor_effect_boundary_sha256: str | None = None
    fallback_plan_ref: str | None = None
    fallback_plan_sha256: str | None = None
    operator_identity_ref: str | None = None
    operator_identity_sha256: str | None = None
    operator_role: str | None = None
    explicit_confirmation: bool = False
    confirmation_phrase: str | None = None
    idempotency_key: str = Field(min_length=1, max_length=128)
    freshness_check_performed_by_guard: bool = False
    connector_health_checked_by_guard: bool = False
    provider_network_request_performed_by_guard: bool = False
    real_provider_api_called_by_guard: bool = False
    runtime_ingest_performed_by_guard: bool = False
    safety_api_called: bool = False
    phase1_l0_l4_state_mutated: bool = False
    credential_material_embedded: bool = False
    raw_location_payload_embedded: bool = False
    raw_provider_payload_embedded: bool = False

    @model_validator(mode="after")
    def enforce_freshness_attestor_invocation_request(
        self,
    ) -> "ProductionLiveFreshnessAttestorInvocationRequest":
        _assert_ref_prefix(
            "source_path",
            self.source_path,
            _PRODUCTION_LIVE_ATTESTATION_PREFIXES,
        )
        if self.source_observation_path is not None:
            _assert_production_live_source(
                self.source_provider,
                self.source_observation_path,
            )
        _assert_ref_prefix(
            "route_scope_ref",
            self.route_scope_ref,
            _PRODUCTION_LIVE_OBSERVATION_REF_PREFIXES,
        )
        if self.provider_request_ref is not None:
            _assert_ref_prefix(
                "provider_request_ref",
                self.provider_request_ref,
                _PRODUCTION_LIVE_OBSERVATION_REF_PREFIXES,
            )
        if self.provider_evidence_ref is not None:
            _assert_ref_prefix(
                "provider_evidence_ref",
                self.provider_evidence_ref,
                _PRODUCTION_LIVE_OBSERVATION_REF_PREFIXES,
            )
        for field_name, value in (
            (
                "reviewed_freshness_attestor_effect_boundary_ref",
                self.reviewed_freshness_attestor_effect_boundary_ref,
            ),
            ("fallback_plan_ref", self.fallback_plan_ref),
            ("operator_identity_ref", self.operator_identity_ref),
        ):
            if value is not None:
                _assert_ref_prefix(
                    field_name,
                    value,
                    _PRODUCTION_LIVE_ATTESTATION_PREFIXES,
                )
        if (
            self.reviewed_freshness_attestor_effect_boundary_ref is None
        ) != (self.reviewed_freshness_attestor_effect_boundary_sha256 is None):
            raise ValueError("freshness attestor effect boundary ref and sha256 must be paired")
        if (self.fallback_plan_ref is None) != (self.fallback_plan_sha256 is None):
            raise ValueError("fallback plan ref and sha256 must be paired")
        if (self.operator_identity_ref is None) != (
            self.operator_identity_sha256 is None
        ):
            raise ValueError("operator identity ref and sha256 must be paired")
        if (self.provider_evidence_ref is None) != (
            self.provider_evidence_sha256 is None
        ):
            raise ValueError("provider evidence ref and sha256 must be paired")
        if (
            self.freshness_check_performed_by_guard
            or self.connector_health_checked_by_guard
            or self.provider_network_request_performed_by_guard
            or self.real_provider_api_called_by_guard
            or self.runtime_ingest_performed_by_guard
            or self.safety_api_called
            or self.phase1_l0_l4_state_mutated
        ):
            raise ValueError("freshness attestor invocation request cannot perform effects")
        if self.credential_material_embedded:
            raise ValueError("freshness attestor invocation request cannot embed credentials")
        if self.raw_location_payload_embedded or self.raw_provider_payload_embedded:
            raise ValueError("freshness attestor invocation request cannot embed raw payloads")
        return self


class ProductionLiveFreshnessAttestorInvocationReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_production_live_freshness_attestor_invocation_receipt"
    artifact_version: str = "production_live_freshness_attestor_invocation_receipt.v0"
    source_provider: str = "scout_runtime_safety_gate_adapters"
    source_path: str
    sha256: str
    status: ProductionLiveFreshnessAttestorInvocationStatus
    gate_id: ProductionLiveProviderGateId
    freshness_attestor_invocation_request_sha256: str
    source_observation_path: str | None = None
    route_scope_ref: str
    provider_request_ref: str | None = None
    provider_response_receipt_sha256: str | None = None
    provider_evidence_ref: str | None = None
    provider_evidence_sha256: str | None = None
    freshness_requirement_minutes: int = Field(gt=0)
    reviewed_freshness_attestor_effect_boundary_ref: str | None = None
    reviewed_freshness_attestor_effect_boundary_sha256: str | None = None
    fallback_plan_ref: str | None = None
    fallback_plan_sha256: str | None = None
    operator_identity_ref: str | None = None
    operator_identity_sha256: str | None = None
    operator_role: str | None = None
    idempotency_key: str
    freshness_attestation_execution_ref: str | None = None
    freshness_attestation_execution_sha256: str | None = None
    freshness_attestor_effect_boundary_present: bool = False
    freshness_attestor_input_evidence_present: bool = False
    fallback_plan_present: bool = False
    operator_identity_present: bool = False
    explicit_confirmation_present: bool = False
    freshness_attestor_invocation_authorized: bool = False
    freshness_check_performed_by_guard: bool = False
    connector_health_checked_by_guard: bool = False
    provider_network_request_performed_by_guard: bool = False
    real_provider_api_called_by_guard: bool = False
    runtime_ingest_performed_by_guard: bool = False
    safety_api_called: bool = False
    phase1_l0_l4_state_mutated: bool = False
    blockers: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    boundary: ProductionLiveFreshnessAttestorInvocationBoundary = Field(
        default_factory=ProductionLiveFreshnessAttestorInvocationBoundary
    )

    @model_validator(mode="after")
    def enforce_freshness_attestor_invocation_receipt(
        self,
    ) -> "ProductionLiveFreshnessAttestorInvocationReceipt":
        authorized = self.status == "freshness_attestor_invocation_authorized"
        if self.freshness_attestor_invocation_authorized != authorized:
            raise ValueError("freshness attestor invocation authorization must match status")
        if authorized and not (
            self.freshness_attestor_effect_boundary_present
            and self.freshness_attestor_input_evidence_present
            and self.fallback_plan_present
            and self.operator_identity_present
            and self.explicit_confirmation_present
            and self.freshness_attestation_execution_ref
            and self.freshness_attestation_execution_sha256
        ):
            raise ValueError("authorized freshness attestor invocation requires all gates")
        if self.freshness_attestation_execution_ref is not None:
            _assert_ref_prefix(
                "freshness_attestation_execution_ref",
                self.freshness_attestation_execution_ref,
                _PRODUCTION_LIVE_ATTESTATION_PREFIXES,
            )
        if (
            self.freshness_check_performed_by_guard
            or self.connector_health_checked_by_guard
            or self.provider_network_request_performed_by_guard
            or self.real_provider_api_called_by_guard
            or self.runtime_ingest_performed_by_guard
            or self.safety_api_called
            or self.phase1_l0_l4_state_mutated
        ):
            raise ValueError("freshness attestor invocation receipt cannot perform effects")
        return self


class ProductionLiveFreshnessAttestationBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deterministic_intake_only: bool = True
    freshness_check_performed_by_intake: bool = False
    connector_health_checked_by_intake: bool = False
    provider_network_request_performed_by_intake: bool = False
    real_provider_api_called_by_intake: bool = False
    runtime_ingest_performed_by_intake: bool = False
    safety_api_called: bool = False
    phase1_l0_l4_state_mutated: bool = False
    credential_material_embedded: bool = False
    raw_location_payload_embedded: bool = False
    raw_provider_payload_embedded: bool = False

    @model_validator(mode="after")
    def enforce_freshness_attestation_boundary(
        self,
    ) -> "ProductionLiveFreshnessAttestationBoundary":
        if not self.deterministic_intake_only:
            raise ValueError("freshness attestation intake must be deterministic")
        if (
            self.freshness_check_performed_by_intake
            or self.connector_health_checked_by_intake
            or self.provider_network_request_performed_by_intake
            or self.real_provider_api_called_by_intake
            or self.runtime_ingest_performed_by_intake
            or self.safety_api_called
            or self.phase1_l0_l4_state_mutated
        ):
            raise ValueError("freshness attestation intake cannot perform effects")
        if self.credential_material_embedded:
            raise ValueError("freshness attestation intake cannot embed credentials")
        if self.raw_location_payload_embedded or self.raw_provider_payload_embedded:
            raise ValueError("freshness attestation intake cannot embed raw payloads")
        return self


class ProductionLiveFreshnessAttestationReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_production_live_freshness_attestation_receipt"
    artifact_version: str = "production_live_freshness_attestation_receipt.v0"
    source_provider: str = Field(min_length=1)
    source_path: str = Field(min_length=1)
    gate_id: ProductionLiveProviderGateId
    source_observation_path: str | None = None
    route_scope_ref: str = Field(min_length=1)
    provider_request_ref: str | None = None
    provider_response_receipt_sha256: str | None = None
    provider_evidence_ref: str | None = None
    provider_evidence_sha256: str | None = None
    freshness_attestor_invocation_sha256: str | None = None
    freshness_attestation_execution_ref: str | None = None
    freshness_attestation_execution_sha256: str | None = None
    freshness_attestation_ref: str | None = None
    freshness_attestation_sha256: str | None = None
    source_age_minutes: float = Field(ge=0)
    freshness_requirement_minutes: int = Field(default=180, gt=0)
    freshness_status: ProductionLiveFreshnessAttestationStatus = "unknown"
    attested_current: bool = False
    route_context: SafetyGateRouteContext = Field(default_factory=SafetyGateRouteContext)
    confidence: SafetyGateConfidence = "medium"
    executor_reported_freshness_check_performed: bool = False
    executor_reported_provider_network_request_performed: bool = False
    executor_reported_real_provider_api_called: bool = False
    executor_reported_runtime_ingest_performed: bool = False
    executor_reported_safety_api_called: bool = False
    executor_reported_phase1_l0_l4_state_mutated: bool = False
    credential_material_embedded: bool = False
    raw_location_payload_embedded: bool = False
    raw_provider_payload_embedded: bool = False

    @model_validator(mode="after")
    def enforce_freshness_attestation_receipt(
        self,
    ) -> "ProductionLiveFreshnessAttestationReceipt":
        _assert_ref_prefix(
            "source_path",
            self.source_path,
            _PRODUCTION_LIVE_ATTESTATION_PREFIXES,
        )
        if self.source_observation_path is not None:
            _assert_production_live_source(
                self.source_provider,
                self.source_observation_path,
            )
        _assert_ref_prefix(
            "route_scope_ref",
            self.route_scope_ref,
            _PRODUCTION_LIVE_OBSERVATION_REF_PREFIXES,
        )
        if self.provider_request_ref is not None:
            _assert_ref_prefix(
                "provider_request_ref",
                self.provider_request_ref,
                _PRODUCTION_LIVE_OBSERVATION_REF_PREFIXES,
            )
        if self.provider_evidence_ref is not None:
            _assert_ref_prefix(
                "provider_evidence_ref",
                self.provider_evidence_ref,
                _PRODUCTION_LIVE_OBSERVATION_REF_PREFIXES,
            )
        if self.freshness_attestation_execution_ref is not None:
            _assert_ref_prefix(
                "freshness_attestation_execution_ref",
                self.freshness_attestation_execution_ref,
                _PRODUCTION_LIVE_ATTESTATION_PREFIXES,
            )
        if (self.freshness_attestation_execution_ref is None) != (
            self.freshness_attestation_execution_sha256 is None
        ):
            raise ValueError(
                "freshness attestation execution ref and sha256 must be paired"
            )
        if self.freshness_attestation_ref is not None:
            _assert_ref_prefix(
                "freshness_attestation_ref",
                self.freshness_attestation_ref,
                _PRODUCTION_LIVE_ATTESTATION_PREFIXES,
            )
        _assert_route_scope(self.route_context)
        if (
            self.executor_reported_runtime_ingest_performed
            or self.executor_reported_safety_api_called
            or self.executor_reported_phase1_l0_l4_state_mutated
        ):
            raise ValueError("freshness attestation receipt cannot claim runtime effects")
        if self.credential_material_embedded:
            raise ValueError("freshness attestation receipt cannot embed credentials")
        if self.raw_location_payload_embedded or self.raw_provider_payload_embedded:
            raise ValueError("freshness attestation receipt cannot embed raw payloads")
        return self


class ProductionLiveFreshnessAttestationDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_production_live_freshness_attestation_intake"
    artifact_version: str = "production_live_freshness_attestation_intake.v0"
    source_provider: str = "scout_runtime_safety_gate_adapters"
    source_path: str
    sha256: str
    status: ProductionLiveFreshnessAttestationIntakeStatus
    gate_id: ProductionLiveProviderGateId
    freshness_receipt_sha256: str
    provider_response_receipt_sha256: str | None = None
    source_observation_path: str | None = None
    route_scope_ref: str
    provider_request_ref: str | None = None
    provider_evidence_ref: str | None = None
    provider_evidence_sha256: str | None = None
    freshness_attestor_invocation_sha256: str | None = None
    freshness_attestation_execution_ref: str | None = None
    freshness_attestation_execution_sha256: str | None = None
    freshness_attestation_ref: str | None = None
    freshness_attestation_sha256: str | None = None
    source_age_minutes: float = Field(ge=0)
    freshness_requirement_minutes: int = Field(gt=0)
    freshness_status: ProductionLiveFreshnessAttestationStatus
    freshness_check_performed: bool = False
    freshness_evidence_present: bool = False
    freshness_attestor_invocation_authorized: bool = False
    freshness_attestor_invocation_lineage_match: bool = False
    freshness_attestation_current: bool = False
    freshness_attestation_prepared: bool = False
    freshness_check_performed_by_intake: bool = False
    connector_health_checked_by_intake: bool = False
    provider_network_request_performed_by_intake: bool = False
    real_provider_api_called_by_intake: bool = False
    runtime_ingest_performed_by_intake: bool = False
    safety_api_called: bool = False
    phase1_l0_l4_state_mutated: bool = False
    blockers: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    boundary: ProductionLiveFreshnessAttestationBoundary = Field(
        default_factory=ProductionLiveFreshnessAttestationBoundary
    )

    @model_validator(mode="after")
    def enforce_freshness_attestation_decision(
        self,
    ) -> "ProductionLiveFreshnessAttestationDecision":
        prepared = self.status == "freshness_attestation_prepared"
        if self.freshness_attestation_prepared != prepared:
            raise ValueError("freshness_attestation_prepared must match status")
        if prepared and not (
            self.freshness_check_performed
            and self.freshness_evidence_present
            and self.freshness_attestation_current
            and self.freshness_attestation_ref
            and self.freshness_attestation_sha256
        ):
            raise ValueError("prepared freshness attestation requires all checks")
        if (
            self.freshness_check_performed_by_intake
            or self.connector_health_checked_by_intake
            or self.provider_network_request_performed_by_intake
            or self.real_provider_api_called_by_intake
            or self.runtime_ingest_performed_by_intake
            or self.safety_api_called
            or self.phase1_l0_l4_state_mutated
        ):
            raise ValueError("freshness attestation intake cannot perform effects")
        return self


class ProductionLiveFreshnessAttestationExecutionBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reviewed_freshness_attestor_effect_boundary_required: bool = True
    injected_freshness_attestation_client_required: bool = True
    freshness_check_allowed: bool = True
    provider_network_request_performed_by_executor: bool = False
    real_provider_api_called_by_executor: bool = False
    runtime_ingest_performed_by_executor: bool = False
    safety_api_called: bool = False
    phase1_l0_l4_state_mutated: bool = False
    outbound_transport_invoked: bool = False
    hardware_control_performed: bool = False
    credential_material_embedded: bool = False
    raw_location_payload_embedded: bool = False
    raw_provider_payload_embedded: bool = False

    @model_validator(mode="after")
    def enforce_freshness_attestation_execution_boundary(
        self,
    ) -> "ProductionLiveFreshnessAttestationExecutionBoundary":
        if not self.reviewed_freshness_attestor_effect_boundary_required:
            raise ValueError("freshness executor requires a reviewed boundary")
        if not self.injected_freshness_attestation_client_required:
            raise ValueError("freshness executor requires an injected client")
        if not self.freshness_check_allowed:
            raise ValueError("freshness executor must allow freshness checks")
        if (
            self.provider_network_request_performed_by_executor
            or self.real_provider_api_called_by_executor
            or self.runtime_ingest_performed_by_executor
            or self.safety_api_called
            or self.phase1_l0_l4_state_mutated
            or self.outbound_transport_invoked
            or self.hardware_control_performed
        ):
            raise ValueError("freshness executor boundary cannot perform runtime effects")
        if self.credential_material_embedded:
            raise ValueError("freshness executor boundary cannot embed credentials")
        if self.raw_location_payload_embedded or self.raw_provider_payload_embedded:
            raise ValueError("freshness executor boundary cannot embed raw payloads")
        return self


class ProductionLiveFreshnessAttestationExecutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_production_live_freshness_attestation_execution_request"
    artifact_version: str = "production_live_freshness_attestation_execution_request.v0"
    gate_id: ProductionLiveProviderGateId
    freshness_attestor_invocation_sha256: str = Field(min_length=1)
    freshness_attestor_invocation_request_sha256: str = Field(min_length=1)
    source_observation_path: str | None = None
    route_scope_ref: str = Field(min_length=1)
    provider_request_ref: str | None = None
    provider_response_receipt_sha256: str | None = None
    provider_evidence_ref: str = Field(min_length=1)
    provider_evidence_sha256: str = Field(min_length=1)
    freshness_requirement_minutes: int = Field(default=180, gt=0)
    freshness_attestation_execution_ref: str = Field(min_length=1)
    freshness_attestation_execution_sha256: str = Field(min_length=1)
    reviewed_freshness_attestor_effect_boundary_ref: str = Field(min_length=1)
    reviewed_freshness_attestor_effect_boundary_sha256: str = Field(min_length=1)
    fallback_plan_ref: str = Field(min_length=1)
    fallback_plan_sha256: str = Field(min_length=1)
    operator_identity_ref: str | None = None
    operator_identity_sha256: str | None = None
    operator_role: str | None = None
    idempotency_key: str = Field(min_length=1, max_length=128)
    provider_network_request_performed_by_executor: bool = False
    real_provider_api_called_by_executor: bool = False
    runtime_ingest_performed_by_executor: bool = False
    safety_api_called: bool = False
    phase1_l0_l4_state_mutated: bool = False
    outbound_transport_invoked: bool = False
    hardware_control_performed: bool = False
    credential_material_embedded: bool = False
    raw_location_payload_embedded: bool = False
    raw_provider_payload_embedded: bool = False
    boundary: ProductionLiveFreshnessAttestationExecutionBoundary = Field(
        default_factory=ProductionLiveFreshnessAttestationExecutionBoundary
    )

    @model_validator(mode="after")
    def enforce_freshness_attestation_execution_request(
        self,
    ) -> "ProductionLiveFreshnessAttestationExecutionRequest":
        if self.source_observation_path is not None:
            _assert_ref_prefix(
                "source_observation_path",
                self.source_observation_path,
                _PRODUCTION_LIVE_OBSERVATION_REF_PREFIXES,
            )
        _assert_ref_prefix(
            "route_scope_ref",
            self.route_scope_ref,
            _PRODUCTION_LIVE_OBSERVATION_REF_PREFIXES,
        )
        for field_name, value, prefixes in (
            (
                "provider_request_ref",
                self.provider_request_ref,
                _PRODUCTION_LIVE_OBSERVATION_REF_PREFIXES,
            ),
            (
                "provider_evidence_ref",
                self.provider_evidence_ref,
                _PRODUCTION_LIVE_OBSERVATION_REF_PREFIXES,
            ),
            (
                "freshness_attestation_execution_ref",
                self.freshness_attestation_execution_ref,
                _PRODUCTION_LIVE_ATTESTATION_PREFIXES,
            ),
            (
                "reviewed_freshness_attestor_effect_boundary_ref",
                self.reviewed_freshness_attestor_effect_boundary_ref,
                _PRODUCTION_LIVE_ATTESTATION_PREFIXES,
            ),
            (
                "fallback_plan_ref",
                self.fallback_plan_ref,
                _PRODUCTION_LIVE_ATTESTATION_PREFIXES,
            ),
            (
                "operator_identity_ref",
                self.operator_identity_ref,
                _PRODUCTION_LIVE_ATTESTATION_PREFIXES,
            ),
        ):
            if value is not None:
                _assert_ref_prefix(field_name, value, prefixes)
        if (
            self.provider_network_request_performed_by_executor
            or self.real_provider_api_called_by_executor
            or self.runtime_ingest_performed_by_executor
            or self.safety_api_called
            or self.phase1_l0_l4_state_mutated
            or self.outbound_transport_invoked
            or self.hardware_control_performed
        ):
            raise ValueError("freshness execution request cannot perform runtime effects")
        if self.credential_material_embedded:
            raise ValueError("freshness execution request cannot embed credentials")
        if self.raw_location_payload_embedded or self.raw_provider_payload_embedded:
            raise ValueError("freshness execution request cannot embed raw payloads")
        return self


class ProductionLiveFreshnessAttestationExecutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_production_live_freshness_attestation_execution_result"
    artifact_version: str = "production_live_freshness_attestation_execution_result.v0"
    source_provider: str = Field(min_length=1)
    source_path: str = Field(min_length=1)
    gate_id: ProductionLiveProviderGateId
    source_observation_path: str | None = None
    route_scope_ref: str = Field(min_length=1)
    provider_request_ref: str | None = None
    provider_response_receipt_sha256: str | None = None
    provider_evidence_ref: str = Field(min_length=1)
    provider_evidence_sha256: str = Field(min_length=1)
    freshness_attestation_ref: str | None = None
    freshness_attestation_sha256: str | None = None
    source_age_minutes: float = Field(ge=0)
    freshness_requirement_minutes: int = Field(default=180, gt=0)
    freshness_status: ProductionLiveFreshnessAttestationStatus = "unknown"
    attested_current: bool = False
    route_context: SafetyGateRouteContext = Field(default_factory=SafetyGateRouteContext)
    confidence: SafetyGateConfidence = "medium"
    executor_reported_freshness_check_performed: bool = False
    executor_reported_provider_network_request_performed: bool = False
    executor_reported_real_provider_api_called: bool = False
    executor_reported_runtime_ingest_performed: bool = False
    executor_reported_safety_api_called: bool = False
    executor_reported_phase1_l0_l4_state_mutated: bool = False
    credential_material_embedded: bool = False
    raw_location_payload_embedded: bool = False
    raw_provider_payload_embedded: bool = False

    @model_validator(mode="after")
    def enforce_freshness_attestation_execution_result(
        self,
    ) -> "ProductionLiveFreshnessAttestationExecutionResult":
        _assert_ref_prefix(
            "source_path",
            self.source_path,
            _PRODUCTION_LIVE_ATTESTATION_PREFIXES,
        )
        if self.source_observation_path is not None:
            _assert_ref_prefix(
                "source_observation_path",
                self.source_observation_path,
                _PRODUCTION_LIVE_OBSERVATION_REF_PREFIXES,
            )
        _assert_ref_prefix(
            "route_scope_ref",
            self.route_scope_ref,
            _PRODUCTION_LIVE_OBSERVATION_REF_PREFIXES,
        )
        _assert_ref_prefix(
            "provider_evidence_ref",
            self.provider_evidence_ref,
            _PRODUCTION_LIVE_OBSERVATION_REF_PREFIXES,
        )
        if self.provider_request_ref is not None:
            _assert_ref_prefix(
                "provider_request_ref",
                self.provider_request_ref,
                _PRODUCTION_LIVE_OBSERVATION_REF_PREFIXES,
            )
        if self.freshness_attestation_ref is not None:
            _assert_ref_prefix(
                "freshness_attestation_ref",
                self.freshness_attestation_ref,
                _PRODUCTION_LIVE_ATTESTATION_PREFIXES,
            )
        _assert_route_scope(self.route_context)
        if (
            self.executor_reported_provider_network_request_performed
            or self.executor_reported_real_provider_api_called
            or self.executor_reported_runtime_ingest_performed
            or self.executor_reported_safety_api_called
            or self.executor_reported_phase1_l0_l4_state_mutated
        ):
            raise ValueError("freshness execution result cannot claim runtime effects")
        if self.credential_material_embedded:
            raise ValueError("freshness execution result cannot embed credentials")
        if self.raw_location_payload_embedded or self.raw_provider_payload_embedded:
            raise ValueError("freshness execution result cannot embed raw payloads")
        return self


class ProductionLiveFreshnessAttestationExecutionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_production_live_freshness_attestation_execution_decision"
    artifact_version: str = "production_live_freshness_attestation_execution_decision.v0"
    source_provider: str = "scout_runtime_safety_gate_adapters"
    source_path: str
    sha256: str
    status: ProductionLiveFreshnessAttestationExecutionStatus
    gate_id: ProductionLiveProviderGateId
    freshness_attestor_invocation_sha256: str
    freshness_attestation_execution_ref: str | None = None
    freshness_attestation_execution_sha256: str | None = None
    execution_request_sha256: str | None = None
    freshness_receipt_sha256: str | None = None
    freshness_receipt: ProductionLiveFreshnessAttestationReceipt | None = None
    freshness_attestor_invocation_authorized: bool = False
    freshness_attestation_client_called: bool = False
    freshness_attestation_client_result_valid: bool = False
    freshness_attestation_client_effect_present: bool = False
    provider_network_request_performed_by_executor: bool = False
    real_provider_api_called_by_executor: bool = False
    runtime_ingest_performed_by_executor: bool = False
    safety_api_called: bool = False
    phase1_l0_l4_state_mutated: bool = False
    outbound_transport_invoked: bool = False
    hardware_control_performed: bool = False
    blockers: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    boundary: ProductionLiveFreshnessAttestationExecutionBoundary = Field(
        default_factory=ProductionLiveFreshnessAttestationExecutionBoundary
    )

    @model_validator(mode="after")
    def enforce_freshness_attestation_execution_decision(
        self,
    ) -> "ProductionLiveFreshnessAttestationExecutionDecision":
        emitted = self.status == "freshness_attestation_receipt_emitted"
        if emitted and not (
            self.freshness_receipt
            and self.freshness_receipt_sha256
            and self.execution_request_sha256
            and self.freshness_attestor_invocation_authorized
            and self.freshness_attestation_client_called
            and self.freshness_attestation_client_result_valid
            and self.freshness_attestation_client_effect_present
        ):
            raise ValueError("emitted freshness attestation receipt requires all gates")
        if not emitted and (self.freshness_receipt or self.freshness_receipt_sha256):
            raise ValueError("blocked freshness execution cannot include receipt")
        if (
            self.provider_network_request_performed_by_executor
            or self.real_provider_api_called_by_executor
            or self.runtime_ingest_performed_by_executor
            or self.safety_api_called
            or self.phase1_l0_l4_state_mutated
            or self.outbound_transport_invoked
            or self.hardware_control_performed
        ):
            raise ValueError("freshness execution decision cannot perform runtime effects")
        return self


class ProductionLiveProviderExecutorReadinessBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deterministic_readiness_only: bool = True
    connector_health_checked_by_readiness: bool = False
    provider_network_request_performed_by_readiness: bool = False
    real_provider_api_called_by_readiness: bool = False
    runtime_ingest_performed_by_readiness: bool = False
    safety_api_called: bool = False
    phase1_l0_l4_state_mutated: bool = False
    credential_material_embedded: bool = False
    raw_location_payload_embedded: bool = False
    raw_provider_payload_embedded: bool = False

    @model_validator(mode="after")
    def enforce_provider_executor_readiness_boundary(
        self,
    ) -> "ProductionLiveProviderExecutorReadinessBoundary":
        if not self.deterministic_readiness_only:
            raise ValueError("provider executor readiness must be deterministic")
        if (
            self.connector_health_checked_by_readiness
            or self.provider_network_request_performed_by_readiness
            or self.real_provider_api_called_by_readiness
            or self.runtime_ingest_performed_by_readiness
            or self.safety_api_called
            or self.phase1_l0_l4_state_mutated
        ):
            raise ValueError("provider executor readiness cannot perform effects")
        if self.credential_material_embedded:
            raise ValueError("provider executor readiness cannot embed credentials")
        if self.raw_location_payload_embedded or self.raw_provider_payload_embedded:
            raise ValueError("provider executor readiness cannot embed raw payloads")
        return self


class ProductionLiveProviderExecutorEffectBoundaryManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = (
        "scout_production_live_provider_executor_effect_boundary_manifest"
    )
    artifact_version: str = (
        "production_live_provider_executor_effect_boundary_manifest.v0"
    )
    source_provider: str = Field(min_length=1)
    source_path: str = Field(min_length=1)
    gate_id: ProductionLiveProviderGateId
    connector_id: str = Field(min_length=1)
    provider_request_readiness_sha256: str = Field(min_length=1)
    connector_manifest_sha256: str = Field(min_length=1)
    request_contract_sha256: str = Field(min_length=1)
    source_observation_path: str = Field(min_length=1)
    route_scope_ref: str = Field(min_length=1)
    connector_health_ref: str | None = None
    connector_health_sha256: str | None = None
    credential_ref: str | None = None
    provider_request_ref: str = Field(min_length=1)
    provider_request_sha256: str = Field(min_length=1)
    provider_effect_boundary_ref: str | None = None
    provider_effect_boundary_sha256: str | None = None
    response_verifier_ref: str | None = None
    response_verifier_sha256: str | None = None
    freshness_attestor_ref: str | None = None
    freshness_attestor_sha256: str | None = None
    field_device_validator_ref: str | None = None
    field_device_validator_sha256: str | None = None
    fallback_plan_ref: str | None = None
    fallback_plan_sha256: str | None = None
    idempotency_key: str = Field(min_length=1, max_length=128)
    connector_health_checked_by_readiness: bool = False
    provider_network_request_performed_by_readiness: bool = False
    real_provider_api_called_by_readiness: bool = False
    runtime_ingest_performed_by_readiness: bool = False
    safety_api_called: bool = False
    phase1_l0_l4_state_mutated: bool = False
    credential_material_embedded: bool = False
    raw_location_payload_embedded: bool = False
    raw_provider_payload_embedded: bool = False

    @model_validator(mode="after")
    def enforce_provider_executor_manifest(
        self,
    ) -> "ProductionLiveProviderExecutorEffectBoundaryManifest":
        _assert_ref_prefix(
            "source_path",
            self.source_path,
            _PRODUCTION_LIVE_ATTESTATION_PREFIXES,
        )
        _assert_production_live_source(
            self.source_provider,
            self.source_observation_path,
        )
        _assert_ref_prefix(
            "route_scope_ref",
            self.route_scope_ref,
            _PRODUCTION_LIVE_OBSERVATION_REF_PREFIXES,
        )
        if self.connector_health_ref is not None:
            _assert_ref_prefix(
                "connector_health_ref",
                self.connector_health_ref,
                _PRODUCTION_LIVE_ATTESTATION_PREFIXES,
            )
        if self.credential_ref is not None:
            _assert_secret_ref(self.credential_ref)
        _assert_ref_prefix(
            "provider_request_ref",
            self.provider_request_ref,
            _PRODUCTION_LIVE_OBSERVATION_REF_PREFIXES,
        )
        for field_name, value in (
            ("provider_effect_boundary_ref", self.provider_effect_boundary_ref),
            ("response_verifier_ref", self.response_verifier_ref),
            ("freshness_attestor_ref", self.freshness_attestor_ref),
            ("field_device_validator_ref", self.field_device_validator_ref),
            ("fallback_plan_ref", self.fallback_plan_ref),
        ):
            if value is not None:
                _assert_ref_prefix(
                    field_name,
                    value,
                    _PRODUCTION_LIVE_ATTESTATION_PREFIXES,
                )
        if (
            self.connector_health_checked_by_readiness
            or self.provider_network_request_performed_by_readiness
            or self.real_provider_api_called_by_readiness
            or self.runtime_ingest_performed_by_readiness
            or self.safety_api_called
            or self.phase1_l0_l4_state_mutated
        ):
            raise ValueError("provider executor manifest cannot perform effects")
        if self.credential_material_embedded:
            raise ValueError("provider executor manifest cannot embed credentials")
        if self.raw_location_payload_embedded or self.raw_provider_payload_embedded:
            raise ValueError("provider executor manifest cannot embed raw payloads")
        return self


class ProductionLiveProviderExecutorReadinessDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_production_live_provider_executor_readiness"
    artifact_version: str = "production_live_provider_executor_readiness.v0"
    source_provider: str = "scout_runtime_safety_gate_adapters"
    source_path: str
    sha256: str
    status: ProductionLiveProviderExecutorReadinessStatus
    gate_id: ProductionLiveProviderGateId
    connector_id: str
    provider_request_readiness_sha256: str
    provider_executor_manifest_sha256: str
    connector_manifest_sha256: str
    request_contract_sha256: str
    source_observation_path: str
    route_scope_ref: str
    provider_request_ref: str | None = None
    provider_request_sha256: str | None = None
    credential_ref_present: bool = False
    provider_effect_boundary_ref: str | None = None
    provider_effect_boundary_sha256: str | None = None
    response_verifier_ref: str | None = None
    response_verifier_sha256: str | None = None
    freshness_attestor_ref: str | None = None
    freshness_attestor_sha256: str | None = None
    field_device_validator_ref: str | None = None
    field_device_validator_sha256: str | None = None
    fallback_plan_ref: str | None = None
    fallback_plan_sha256: str | None = None
    provider_request_authorized: bool = False
    lineage_match: bool = False
    provider_executor_boundary_present: bool = False
    response_verifier_present: bool = False
    freshness_attestor_present: bool = False
    field_device_validator_present: bool = False
    fallback_plan_present: bool = False
    ready_for_reviewed_provider_effect_boundary: bool = False
    connector_health_checked_by_readiness: bool = False
    provider_network_request_performed_by_readiness: bool = False
    real_provider_api_called_by_readiness: bool = False
    runtime_ingest_performed_by_readiness: bool = False
    safety_api_called: bool = False
    phase1_l0_l4_state_mutated: bool = False
    blockers: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    boundary: ProductionLiveProviderExecutorReadinessBoundary = Field(
        default_factory=ProductionLiveProviderExecutorReadinessBoundary
    )

    @model_validator(mode="after")
    def enforce_provider_executor_readiness(
        self,
    ) -> "ProductionLiveProviderExecutorReadinessDecision":
        ready = self.status == "ready_for_reviewed_provider_effect_boundary"
        if self.ready_for_reviewed_provider_effect_boundary != ready:
            raise ValueError("provider executor readiness must match status")
        if ready and not (
            self.provider_request_authorized
            and self.lineage_match
            and self.provider_executor_boundary_present
            and self.response_verifier_present
            and self.freshness_attestor_present
            and self.field_device_validator_present
            and self.fallback_plan_present
        ):
            raise ValueError("ready provider executor boundary requires all gates")
        if (
            self.connector_health_checked_by_readiness
            or self.provider_network_request_performed_by_readiness
            or self.real_provider_api_called_by_readiness
            or self.runtime_ingest_performed_by_readiness
            or self.safety_api_called
            or self.phase1_l0_l4_state_mutated
        ):
            raise ValueError("provider executor readiness cannot perform effects")
        return self


class ProductionLiveProviderExecutorInvocationBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deterministic_invocation_guard_only: bool = True
    connector_health_checked_by_guard: bool = False
    provider_network_request_performed_by_guard: bool = False
    real_provider_api_called_by_guard: bool = False
    runtime_ingest_performed_by_guard: bool = False
    safety_api_called: bool = False
    phase1_l0_l4_state_mutated: bool = False
    credential_material_embedded: bool = False
    raw_location_payload_embedded: bool = False
    raw_provider_payload_embedded: bool = False

    @model_validator(mode="after")
    def enforce_provider_executor_invocation_boundary(
        self,
    ) -> "ProductionLiveProviderExecutorInvocationBoundary":
        if not self.deterministic_invocation_guard_only:
            raise ValueError("provider executor invocation guard must be deterministic")
        if (
            self.connector_health_checked_by_guard
            or self.provider_network_request_performed_by_guard
            or self.real_provider_api_called_by_guard
            or self.runtime_ingest_performed_by_guard
            or self.safety_api_called
            or self.phase1_l0_l4_state_mutated
        ):
            raise ValueError("provider executor invocation guard cannot perform effects")
        if self.credential_material_embedded:
            raise ValueError("provider executor invocation guard cannot embed credentials")
        if self.raw_location_payload_embedded or self.raw_provider_payload_embedded:
            raise ValueError(
                "provider executor invocation guard cannot embed raw payloads"
            )
        return self


class ProductionLiveProviderExecutorInvocationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_production_live_provider_executor_invocation_request"
    artifact_version: str = "production_live_provider_executor_invocation_request.v0"
    gate_id: ProductionLiveProviderGateId
    connector_id: str = Field(min_length=1)
    provider_executor_readiness_sha256: str = Field(min_length=1)
    provider_request_readiness_sha256: str = Field(min_length=1)
    provider_executor_manifest_sha256: str = Field(min_length=1)
    connector_manifest_sha256: str = Field(min_length=1)
    request_contract_sha256: str = Field(min_length=1)
    source_observation_path: str = Field(min_length=1)
    route_scope_ref: str = Field(min_length=1)
    provider_request_ref: str = Field(min_length=1)
    provider_request_sha256: str = Field(min_length=1)
    provider_effect_boundary_ref: str = Field(min_length=1)
    provider_effect_boundary_sha256: str = Field(min_length=1)
    response_verifier_ref: str = Field(min_length=1)
    response_verifier_sha256: str = Field(min_length=1)
    freshness_attestor_ref: str = Field(min_length=1)
    freshness_attestor_sha256: str = Field(min_length=1)
    field_device_validator_ref: str = Field(min_length=1)
    field_device_validator_sha256: str = Field(min_length=1)
    fallback_plan_ref: str = Field(min_length=1)
    fallback_plan_sha256: str = Field(min_length=1)
    operator_identity_ref: str | None = None
    operator_identity_sha256: str | None = None
    operator_role: str | None = None
    explicit_confirmation: bool = False
    confirmation_phrase: str | None = None
    idempotency_key: str = Field(min_length=1, max_length=128)
    connector_health_checked_by_guard: bool = False
    provider_network_request_performed_by_guard: bool = False
    real_provider_api_called_by_guard: bool = False
    runtime_ingest_performed_by_guard: bool = False
    safety_api_called: bool = False
    phase1_l0_l4_state_mutated: bool = False
    credential_material_embedded: bool = False
    raw_location_payload_embedded: bool = False
    raw_provider_payload_embedded: bool = False

    @model_validator(mode="after")
    def enforce_provider_executor_invocation_request(
        self,
    ) -> "ProductionLiveProviderExecutorInvocationRequest":
        _assert_production_live_source(
            "production_live_provider_executor",
            self.source_observation_path,
        )
        _assert_ref_prefix(
            "route_scope_ref",
            self.route_scope_ref,
            _PRODUCTION_LIVE_OBSERVATION_REF_PREFIXES,
        )
        _assert_ref_prefix(
            "provider_request_ref",
            self.provider_request_ref,
            _PRODUCTION_LIVE_OBSERVATION_REF_PREFIXES,
        )
        for field_name, value in (
            ("provider_effect_boundary_ref", self.provider_effect_boundary_ref),
            ("response_verifier_ref", self.response_verifier_ref),
            ("freshness_attestor_ref", self.freshness_attestor_ref),
            ("field_device_validator_ref", self.field_device_validator_ref),
            ("fallback_plan_ref", self.fallback_plan_ref),
        ):
            _assert_ref_prefix(
                field_name,
                value,
                _PRODUCTION_LIVE_ATTESTATION_PREFIXES,
            )
        if self.operator_identity_ref is not None:
            _assert_ref_prefix(
                "operator_identity_ref",
                self.operator_identity_ref,
                _PRODUCTION_LIVE_ATTESTATION_PREFIXES,
            )
        if (
            self.connector_health_checked_by_guard
            or self.provider_network_request_performed_by_guard
            or self.real_provider_api_called_by_guard
            or self.runtime_ingest_performed_by_guard
            or self.safety_api_called
            or self.phase1_l0_l4_state_mutated
        ):
            raise ValueError("provider executor invocation request cannot perform effects")
        if self.credential_material_embedded:
            raise ValueError("provider executor invocation request cannot embed credentials")
        if self.raw_location_payload_embedded or self.raw_provider_payload_embedded:
            raise ValueError(
                "provider executor invocation request cannot embed raw payloads"
            )
        return self


class ProductionLiveProviderExecutorInvocationReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_production_live_provider_executor_invocation_receipt"
    artifact_version: str = "production_live_provider_executor_invocation_receipt.v0"
    source_provider: str = "scout_runtime_safety_gate_adapters"
    source_path: str
    sha256: str
    status: ProductionLiveProviderExecutorInvocationStatus
    gate_id: ProductionLiveProviderGateId
    connector_id: str
    provider_executor_readiness_sha256: str
    provider_request_readiness_sha256: str
    provider_executor_manifest_sha256: str
    connector_manifest_sha256: str
    request_contract_sha256: str
    invocation_request_sha256: str
    source_observation_path: str
    route_scope_ref: str
    provider_request_ref: str
    provider_request_sha256: str
    provider_effect_boundary_ref: str | None = None
    provider_effect_boundary_sha256: str | None = None
    response_verifier_ref: str | None = None
    response_verifier_sha256: str | None = None
    freshness_attestor_ref: str | None = None
    freshness_attestor_sha256: str | None = None
    field_device_validator_ref: str | None = None
    field_device_validator_sha256: str | None = None
    fallback_plan_ref: str | None = None
    fallback_plan_sha256: str | None = None
    operator_identity_ref: str | None = None
    operator_identity_sha256: str | None = None
    operator_role: str | None = None
    idempotency_key: str
    provider_execution_ref: str | None = None
    provider_execution_sha256: str | None = None
    provider_executor_ready: bool = False
    lineage_match: bool = False
    provider_effect_boundary_present: bool = False
    operator_identity_present: bool = False
    explicit_confirmation_present: bool = False
    provider_executor_invocation_authorized: bool = False
    connector_health_checked_by_guard: bool = False
    provider_network_request_performed_by_guard: bool = False
    real_provider_api_called_by_guard: bool = False
    runtime_ingest_performed_by_guard: bool = False
    safety_api_called: bool = False
    phase1_l0_l4_state_mutated: bool = False
    blockers: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    boundary: ProductionLiveProviderExecutorInvocationBoundary = Field(
        default_factory=ProductionLiveProviderExecutorInvocationBoundary
    )

    @model_validator(mode="after")
    def enforce_provider_executor_invocation_receipt(
        self,
    ) -> "ProductionLiveProviderExecutorInvocationReceipt":
        authorized = self.status == "provider_executor_invocation_authorized"
        if self.provider_executor_invocation_authorized != authorized:
            raise ValueError("provider executor invocation authorization must match status")
        if authorized and not (
            self.provider_executor_ready
            and self.lineage_match
            and self.provider_effect_boundary_present
            and self.operator_identity_present
            and self.explicit_confirmation_present
            and self.provider_execution_ref
            and self.provider_execution_sha256
        ):
            raise ValueError("authorized provider invocation requires all gates")
        if self.provider_execution_ref is not None:
            _assert_ref_prefix(
                "provider_execution_ref",
                self.provider_execution_ref,
                _PRODUCTION_LIVE_OBSERVATION_REF_PREFIXES,
            )
        if (
            self.connector_health_checked_by_guard
            or self.provider_network_request_performed_by_guard
            or self.real_provider_api_called_by_guard
            or self.runtime_ingest_performed_by_guard
            or self.safety_api_called
            or self.phase1_l0_l4_state_mutated
        ):
            raise ValueError("provider executor invocation receipt cannot perform effects")
        return self


class ProductionLiveProviderExecutionBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reviewed_provider_effect_boundary_required: bool = True
    injected_provider_client_required: bool = True
    provider_network_request_allowed: bool = True
    real_provider_api_call_allowed: bool = True
    connector_health_checked_by_executor: bool = False
    runtime_ingest_performed_by_executor: bool = False
    safety_api_called: bool = False
    phase1_l0_l4_state_mutated: bool = False
    outbound_transport_invoked: bool = False
    hardware_control_performed: bool = False
    credential_material_embedded: bool = False
    raw_location_payload_embedded: bool = False
    raw_provider_payload_embedded: bool = False

    @model_validator(mode="after")
    def enforce_provider_execution_boundary(
        self,
    ) -> "ProductionLiveProviderExecutionBoundary":
        if not self.reviewed_provider_effect_boundary_required:
            raise ValueError("provider executor requires a reviewed effect boundary")
        if not self.injected_provider_client_required:
            raise ValueError("provider executor requires an injected provider client")
        if not (
            self.provider_network_request_allowed
            and self.real_provider_api_call_allowed
        ):
            raise ValueError("provider executor boundary must allow only provider API effects")
        if (
            self.connector_health_checked_by_executor
            or self.runtime_ingest_performed_by_executor
            or self.safety_api_called
            or self.phase1_l0_l4_state_mutated
            or self.outbound_transport_invoked
            or self.hardware_control_performed
        ):
            raise ValueError("provider executor boundary cannot perform runtime effects")
        if self.credential_material_embedded:
            raise ValueError("provider executor boundary cannot embed credentials")
        if self.raw_location_payload_embedded or self.raw_provider_payload_embedded:
            raise ValueError("provider executor boundary cannot embed raw payloads")
        return self


class ProductionLiveProviderExecutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_production_live_provider_execution_request"
    artifact_version: str = "production_live_provider_execution_request.v0"
    gate_id: ProductionLiveProviderGateId
    connector_id: str = Field(min_length=1)
    provider_executor_invocation_sha256: str = Field(min_length=1)
    provider_executor_readiness_sha256: str = Field(min_length=1)
    provider_request_readiness_sha256: str = Field(min_length=1)
    provider_executor_manifest_sha256: str = Field(min_length=1)
    connector_manifest_sha256: str = Field(min_length=1)
    request_contract_sha256: str = Field(min_length=1)
    source_observation_path: str = Field(min_length=1)
    route_scope_ref: str = Field(min_length=1)
    provider_request_ref: str = Field(min_length=1)
    provider_request_sha256: str = Field(min_length=1)
    provider_execution_ref: str = Field(min_length=1)
    provider_execution_sha256: str = Field(min_length=1)
    provider_dataset_ids: list[str] = Field(default_factory=list)
    provider_effect_boundary_ref: str = Field(min_length=1)
    provider_effect_boundary_sha256: str = Field(min_length=1)
    response_verifier_ref: str = Field(min_length=1)
    response_verifier_sha256: str = Field(min_length=1)
    freshness_attestor_ref: str = Field(min_length=1)
    freshness_attestor_sha256: str = Field(min_length=1)
    field_device_validator_ref: str = Field(min_length=1)
    field_device_validator_sha256: str = Field(min_length=1)
    fallback_plan_ref: str = Field(min_length=1)
    fallback_plan_sha256: str = Field(min_length=1)
    operator_identity_ref: str | None = None
    operator_identity_sha256: str | None = None
    operator_role: str | None = None
    credential_ref_present: bool = True
    idempotency_key: str = Field(min_length=1, max_length=128)
    connector_health_checked_by_executor: bool = False
    runtime_ingest_performed_by_executor: bool = False
    safety_api_called: bool = False
    phase1_l0_l4_state_mutated: bool = False
    outbound_transport_invoked: bool = False
    hardware_control_performed: bool = False
    credential_material_embedded: bool = False
    raw_location_payload_embedded: bool = False
    raw_provider_payload_embedded: bool = False
    boundary: ProductionLiveProviderExecutionBoundary = Field(
        default_factory=ProductionLiveProviderExecutionBoundary
    )

    @model_validator(mode="after")
    def enforce_provider_execution_request(
        self,
    ) -> "ProductionLiveProviderExecutionRequest":
        _assert_production_live_source(
            "production_live_provider_executor",
            self.source_observation_path,
        )
        _assert_ref_prefix(
            "route_scope_ref",
            self.route_scope_ref,
            _PRODUCTION_LIVE_OBSERVATION_REF_PREFIXES,
        )
        _assert_ref_prefix(
            "provider_request_ref",
            self.provider_request_ref,
            _PRODUCTION_LIVE_OBSERVATION_REF_PREFIXES,
        )
        _assert_ref_prefix(
            "provider_execution_ref",
            self.provider_execution_ref,
            _PRODUCTION_LIVE_OBSERVATION_REF_PREFIXES,
        )
        for field_name, value in (
            ("provider_effect_boundary_ref", self.provider_effect_boundary_ref),
            ("response_verifier_ref", self.response_verifier_ref),
            ("freshness_attestor_ref", self.freshness_attestor_ref),
            ("field_device_validator_ref", self.field_device_validator_ref),
            ("fallback_plan_ref", self.fallback_plan_ref),
        ):
            _assert_ref_prefix(
                field_name,
                value,
                _PRODUCTION_LIVE_ATTESTATION_PREFIXES,
            )
        if self.operator_identity_ref is not None:
            _assert_ref_prefix(
                "operator_identity_ref",
                self.operator_identity_ref,
                _PRODUCTION_LIVE_ATTESTATION_PREFIXES,
            )
        if (
            self.connector_health_checked_by_executor
            or self.runtime_ingest_performed_by_executor
            or self.safety_api_called
            or self.phase1_l0_l4_state_mutated
            or self.outbound_transport_invoked
            or self.hardware_control_performed
        ):
            raise ValueError("provider execution request cannot perform runtime effects")
        if self.credential_material_embedded:
            raise ValueError("provider execution request cannot embed credentials")
        if self.raw_location_payload_embedded or self.raw_provider_payload_embedded:
            raise ValueError("provider execution request cannot embed raw payloads")
        return self


class ProductionLiveProviderExecutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_production_live_provider_execution_result"
    artifact_version: str = "production_live_provider_execution_result.v0"
    source_provider: str = Field(min_length=1)
    source_path: str = Field(min_length=1)
    source_observation_path: str = Field(min_length=1)
    provider_dataset_ids: list[str] = Field(default_factory=list)
    provider_evidence_ref: str | None = None
    provider_evidence_sha256: str | None = None
    current_observation_ref: str | None = None
    freshness_attestation_ref: str | None = None
    freshness_attestation_sha256: str | None = None
    source_age_minutes: float = Field(ge=0)
    freshness_requirement_minutes: int = Field(default=180, gt=0)
    response_status: ProductionLiveProviderResponseStatus = "unknown"
    observed_at_offset_s: int = Field(default=0, ge=0)
    warning_level: WeatherGateLevel = "none"
    warning_type: str | None = None
    wind_risk: bool = False
    rain_risk: bool = False
    lightning_risk: bool = False
    threat_type: str | None = None
    passability: EnvironmentThreatPassability = "unknown"
    immediacy: EnvironmentThreatImmediacy = "nearby"
    route_blocked: bool = False
    safe_bypass_known: bool = False
    field_attestation_ref: str | None = None
    device_evidence_ref: str | None = None
    route_pressure_review_required: bool = False
    route_context: SafetyGateRouteContext = Field(default_factory=SafetyGateRouteContext)
    evidence_refs: list[str] = Field(default_factory=list)
    confidence: SafetyGateConfidence = "medium"
    executor_reported_provider_network_request_performed: bool = False
    executor_reported_real_provider_api_called: bool = False
    executor_reported_runtime_ingest_performed: bool = False
    executor_reported_safety_api_called: bool = False
    executor_reported_phase1_l0_l4_state_mutated: bool = False
    credential_material_embedded: bool = False
    raw_location_payload_embedded: bool = False
    raw_provider_payload_embedded: bool = False

    @model_validator(mode="after")
    def enforce_provider_execution_result(
        self,
    ) -> "ProductionLiveProviderExecutionResult":
        _assert_production_live_source(self.source_provider, self.source_path)
        _assert_production_live_source(
            self.source_provider,
            self.source_observation_path,
        )
        if self.provider_evidence_ref is not None:
            _assert_ref_prefix(
                "provider_evidence_ref",
                self.provider_evidence_ref,
                _PRODUCTION_LIVE_OBSERVATION_REF_PREFIXES,
            )
        if self.current_observation_ref is not None:
            _assert_ref_prefix(
                "current_observation_ref",
                self.current_observation_ref,
                _PRODUCTION_LIVE_OBSERVATION_REF_PREFIXES,
            )
        if self.freshness_attestation_ref is not None:
            _assert_ref_prefix(
                "freshness_attestation_ref",
                self.freshness_attestation_ref,
                _PRODUCTION_LIVE_ATTESTATION_PREFIXES,
            )
        if self.field_attestation_ref is not None:
            _assert_ref_prefix(
                "field_attestation_ref",
                self.field_attestation_ref,
                _PRODUCTION_LIVE_ATTESTATION_PREFIXES,
            )
        if self.device_evidence_ref is not None:
            _assert_ref_prefix(
                "device_evidence_ref",
                self.device_evidence_ref,
                _PRODUCTION_LIVE_OBSERVATION_REF_PREFIXES,
            )
        _assert_route_scope(self.route_context)
        if self.route_blocked and self.passability == "passable":
            raise ValueError("route_blocked cannot be passable")
        if (
            self.executor_reported_runtime_ingest_performed
            or self.executor_reported_safety_api_called
            or self.executor_reported_phase1_l0_l4_state_mutated
        ):
            raise ValueError("provider execution result cannot claim runtime effects")
        if self.credential_material_embedded:
            raise ValueError("provider execution result cannot embed credentials")
        if self.raw_location_payload_embedded or self.raw_provider_payload_embedded:
            raise ValueError("provider execution result cannot embed raw payloads")
        return self


class ProductionLiveProviderEffectReceiptIntakeBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deterministic_intake_only: bool = True
    connector_health_checked_by_intake: bool = False
    provider_network_request_performed_by_intake: bool = False
    real_provider_api_called_by_intake: bool = False
    runtime_ingest_performed_by_intake: bool = False
    safety_api_called: bool = False
    phase1_l0_l4_state_mutated: bool = False
    credential_material_embedded: bool = False
    raw_location_payload_embedded: bool = False
    raw_provider_payload_embedded: bool = False

    @model_validator(mode="after")
    def enforce_provider_effect_receipt_intake_boundary(
        self,
    ) -> "ProductionLiveProviderEffectReceiptIntakeBoundary":
        if not self.deterministic_intake_only:
            raise ValueError("provider effect receipt intake must be deterministic")
        if (
            self.connector_health_checked_by_intake
            or self.provider_network_request_performed_by_intake
            or self.real_provider_api_called_by_intake
            or self.runtime_ingest_performed_by_intake
            or self.safety_api_called
            or self.phase1_l0_l4_state_mutated
        ):
            raise ValueError("provider effect receipt intake cannot perform effects")
        if self.credential_material_embedded:
            raise ValueError("provider effect receipt intake cannot embed credentials")
        if self.raw_location_payload_embedded or self.raw_provider_payload_embedded:
            raise ValueError("provider effect receipt intake cannot embed raw payloads")
        return self


class ProductionLiveProviderEffectReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_production_live_provider_effect_receipt"
    artifact_version: str = "production_live_provider_effect_receipt.v0"
    source_provider: str = Field(min_length=1)
    source_path: str = Field(min_length=1)
    gate_id: ProductionLiveProviderGateId
    connector_id: str = Field(min_length=1)
    provider_executor_invocation_sha256: str = Field(min_length=1)
    provider_executor_readiness_sha256: str = Field(min_length=1)
    provider_request_readiness_sha256: str = Field(min_length=1)
    provider_executor_manifest_sha256: str = Field(min_length=1)
    connector_manifest_sha256: str = Field(min_length=1)
    request_contract_sha256: str = Field(min_length=1)
    source_observation_path: str = Field(min_length=1)
    route_scope_ref: str = Field(min_length=1)
    provider_request_ref: str = Field(min_length=1)
    provider_request_sha256: str = Field(min_length=1)
    provider_execution_ref: str = Field(min_length=1)
    provider_execution_sha256: str = Field(min_length=1)
    provider_dataset_ids: list[str] = Field(default_factory=list)
    provider_evidence_ref: str | None = None
    provider_evidence_sha256: str | None = None
    current_observation_ref: str | None = None
    freshness_attestation_ref: str | None = None
    freshness_attestation_sha256: str | None = None
    source_age_minutes: float = Field(ge=0)
    freshness_requirement_minutes: int = Field(default=180, gt=0)
    response_status: ProductionLiveProviderResponseStatus = "unknown"
    observed_at_offset_s: int = Field(default=0, ge=0)
    warning_level: WeatherGateLevel = "none"
    warning_type: str | None = None
    wind_risk: bool = False
    rain_risk: bool = False
    lightning_risk: bool = False
    threat_type: str | None = None
    passability: EnvironmentThreatPassability = "unknown"
    immediacy: EnvironmentThreatImmediacy = "nearby"
    route_blocked: bool = False
    safe_bypass_known: bool = False
    field_attestation_ref: str | None = None
    device_evidence_ref: str | None = None
    route_pressure_review_required: bool = False
    route_context: SafetyGateRouteContext = Field(default_factory=SafetyGateRouteContext)
    evidence_refs: list[str] = Field(default_factory=list)
    confidence: SafetyGateConfidence = "medium"
    executor_reported_provider_network_request_performed: bool = False
    executor_reported_real_provider_api_called: bool = False
    executor_reported_runtime_ingest_performed: bool = False
    executor_reported_safety_api_called: bool = False
    executor_reported_phase1_l0_l4_state_mutated: bool = False
    credential_material_embedded: bool = False
    raw_location_payload_embedded: bool = False
    raw_provider_payload_embedded: bool = False

    @model_validator(mode="after")
    def enforce_provider_effect_receipt(
        self,
    ) -> "ProductionLiveProviderEffectReceipt":
        if self.route_blocked and self.passability == "passable":
            raise ValueError("route_blocked cannot be passable")
        _assert_production_live_source(self.source_provider, self.source_path)
        _assert_production_live_source(
            self.source_provider,
            self.source_observation_path,
        )
        _assert_ref_prefix(
            "route_scope_ref",
            self.route_scope_ref,
            _PRODUCTION_LIVE_OBSERVATION_REF_PREFIXES,
        )
        _assert_ref_prefix(
            "provider_request_ref",
            self.provider_request_ref,
            _PRODUCTION_LIVE_OBSERVATION_REF_PREFIXES,
        )
        _assert_ref_prefix(
            "provider_execution_ref",
            self.provider_execution_ref,
            _PRODUCTION_LIVE_OBSERVATION_REF_PREFIXES,
        )
        if self.provider_evidence_ref is not None:
            _assert_ref_prefix(
                "provider_evidence_ref",
                self.provider_evidence_ref,
                _PRODUCTION_LIVE_OBSERVATION_REF_PREFIXES,
            )
        if self.current_observation_ref is not None:
            _assert_ref_prefix(
                "current_observation_ref",
                self.current_observation_ref,
                _PRODUCTION_LIVE_OBSERVATION_REF_PREFIXES,
            )
        if self.freshness_attestation_ref is not None:
            _assert_ref_prefix(
                "freshness_attestation_ref",
                self.freshness_attestation_ref,
                _PRODUCTION_LIVE_ATTESTATION_PREFIXES,
            )
        if self.field_attestation_ref is not None:
            _assert_ref_prefix(
                "field_attestation_ref",
                self.field_attestation_ref,
                _PRODUCTION_LIVE_ATTESTATION_PREFIXES,
            )
        if self.device_evidence_ref is not None:
            _assert_ref_prefix(
                "device_evidence_ref",
                self.device_evidence_ref,
                _PRODUCTION_LIVE_OBSERVATION_REF_PREFIXES,
            )
        _assert_route_scope(self.route_context)
        if self.gate_id == "environment_threat_gate" and not (
            self.threat_type and self.current_observation_ref
        ):
            raise ValueError(
                "environment threat provider effect requires threat_type and current_observation_ref"
            )
        if (
            self.executor_reported_runtime_ingest_performed
            or self.executor_reported_safety_api_called
            or self.executor_reported_phase1_l0_l4_state_mutated
        ):
            raise ValueError("provider effect receipt cannot claim runtime effects")
        if self.credential_material_embedded:
            raise ValueError("provider effect receipt cannot embed credentials")
        if self.raw_location_payload_embedded or self.raw_provider_payload_embedded:
            raise ValueError("provider effect receipt cannot embed raw payloads")
        return self


class ProductionLiveProviderExecutionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_production_live_provider_execution_decision"
    artifact_version: str = "production_live_provider_execution_decision.v0"
    source_provider: str = "scout_runtime_safety_gate_adapters"
    source_path: str
    sha256: str
    status: ProductionLiveProviderExecutionStatus
    gate_id: ProductionLiveProviderGateId
    connector_id: str
    provider_executor_invocation_sha256: str
    provider_executor_readiness_sha256: str
    provider_request_readiness_sha256: str
    provider_executor_manifest_sha256: str
    connector_manifest_sha256: str
    request_contract_sha256: str
    source_observation_path: str
    route_scope_ref: str
    provider_request_ref: str
    provider_request_sha256: str
    provider_execution_ref: str | None = None
    provider_execution_sha256: str | None = None
    execution_request_sha256: str | None = None
    provider_effect_receipt_sha256: str | None = None
    provider_effect_receipt: ProductionLiveProviderEffectReceipt | None = None
    provider_executor_ready: bool = False
    provider_executor_invocation_authorized: bool = False
    provider_execution_lineage_match: bool = False
    provider_client_called: bool = False
    provider_client_result_valid: bool = False
    provider_client_effect_present: bool = False
    connector_health_checked_by_executor: bool = False
    runtime_ingest_performed_by_executor: bool = False
    safety_api_called: bool = False
    phase1_l0_l4_state_mutated: bool = False
    outbound_transport_invoked: bool = False
    hardware_control_performed: bool = False
    blockers: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    boundary: ProductionLiveProviderExecutionBoundary = Field(
        default_factory=ProductionLiveProviderExecutionBoundary
    )

    @model_validator(mode="after")
    def enforce_provider_execution_decision(
        self,
    ) -> "ProductionLiveProviderExecutionDecision":
        emitted = self.status == "provider_effect_receipt_emitted"
        if emitted and not (
            self.provider_effect_receipt
            and self.provider_effect_receipt_sha256
            and self.execution_request_sha256
            and self.provider_executor_ready
            and self.provider_executor_invocation_authorized
            and self.provider_execution_lineage_match
            and self.provider_client_called
            and self.provider_client_result_valid
            and self.provider_client_effect_present
        ):
            raise ValueError("emitted provider effect receipt requires all gates")
        if not emitted and (self.provider_effect_receipt or self.provider_effect_receipt_sha256):
            raise ValueError("blocked provider execution cannot include effect receipt")
        if (
            self.connector_health_checked_by_executor
            or self.runtime_ingest_performed_by_executor
            or self.safety_api_called
            or self.phase1_l0_l4_state_mutated
            or self.outbound_transport_invoked
            or self.hardware_control_performed
        ):
            raise ValueError("provider execution decision cannot perform runtime effects")
        return self


class ProductionLiveProviderEffectReceiptIntakeDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_production_live_provider_effect_receipt_intake"
    artifact_version: str = "production_live_provider_effect_receipt_intake.v0"
    source_provider: str = "scout_runtime_safety_gate_adapters"
    source_path: str
    sha256: str
    status: ProductionLiveProviderEffectReceiptIntakeStatus
    gate_id: ProductionLiveProviderGateId
    connector_id: str
    provider_effect_receipt_sha256: str
    provider_executor_invocation_sha256: str
    provider_executor_readiness_sha256: str
    provider_request_readiness_sha256: str
    provider_executor_manifest_sha256: str
    connector_manifest_sha256: str
    request_contract_sha256: str
    source_observation_path: str
    route_scope_ref: str
    provider_request_ref: str
    provider_request_sha256: str
    provider_execution_ref: str
    provider_execution_sha256: str
    provider_evidence_ref: str | None = None
    provider_evidence_sha256: str | None = None
    response_receipt_sha256: str | None = None
    response_receipt: ProductionLiveProviderResponseReceipt | None = None
    provider_executor_invocation_authorized: bool = False
    provider_effect_lineage_match: bool = False
    provider_effect_evidence_present: bool = False
    provider_effect_successful: bool = False
    response_receipt_prepared: bool = False
    connector_health_checked_by_intake: bool = False
    provider_network_request_performed_by_intake: bool = False
    real_provider_api_called_by_intake: bool = False
    runtime_ingest_performed_by_intake: bool = False
    safety_api_called: bool = False
    phase1_l0_l4_state_mutated: bool = False
    blockers: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    boundary: ProductionLiveProviderEffectReceiptIntakeBoundary = Field(
        default_factory=ProductionLiveProviderEffectReceiptIntakeBoundary
    )

    @model_validator(mode="after")
    def enforce_provider_effect_receipt_intake(
        self,
    ) -> "ProductionLiveProviderEffectReceiptIntakeDecision":
        prepared = self.status == "provider_response_receipt_prepared"
        if self.response_receipt_prepared != prepared:
            raise ValueError("response_receipt_prepared must match status")
        if prepared and not (
            self.response_receipt
            and self.response_receipt_sha256
            and self.provider_executor_invocation_authorized
            and self.provider_effect_lineage_match
            and self.provider_effect_evidence_present
            and self.provider_effect_successful
        ):
            raise ValueError("prepared provider response receipt requires all gates")
        if not prepared and (self.response_receipt or self.response_receipt_sha256):
            raise ValueError("blocked provider effect intake cannot include response receipt")
        if (
            self.connector_health_checked_by_intake
            or self.provider_network_request_performed_by_intake
            or self.real_provider_api_called_by_intake
            or self.runtime_ingest_performed_by_intake
            or self.safety_api_called
            or self.phase1_l0_l4_state_mutated
        ):
            raise ValueError("provider effect receipt intake cannot perform effects")
        return self


def build_pace_gate_event(
    observation: PaceGateObservation | dict[str, Any],
):
    item = (
        observation
        if isinstance(observation, PaceGateObservation)
        else PaceGateObservation.model_validate(observation)
    )
    ratio = item.observed_segment_minutes / item.reference_p75_segment_minutes
    eta_delay = max(0, round(item.observed_segment_minutes - item.reference_p75_segment_minutes))
    efficiency = item.low_movement_efficiency_ratio
    severity = "none"
    transition = "none"
    state = "on_pace"
    action = "continue_monitoring"
    reasons = [f"segment_time_ratio:{ratio:.2f}"]
    if efficiency is not None:
        reasons.append(f"movement_efficiency_ratio:{efficiency:.2f}")

    if ratio >= 1.65 or (ratio >= 1.45 and item.route_pressure_review_required):
        severity = "retreat_review" if item.route_pressure_review_required else "rest"
        transition = (
            "candidate_retreat"
            if severity == "retreat_review"
            else "candidate_rest"
        )
        state = "pace_collapse_review" if severity == "retreat_review" else "pace_rest_review"
        action = "review_retreat_or_extended_rest" if severity == "retreat_review" else "stop_and_rest"
        reasons.append("observed pace is far slower than reference p75")
    elif ratio >= 1.35 or (efficiency is not None and efficiency < 0.65):
        severity = "rest"
        transition = "candidate_rest"
        state = "pace_rest_review"
        action = "slow_down_or_rest"
        reasons.append("slow pace with movement-efficiency pressure")
    elif ratio >= 1.15:
        severity = "watch"
        transition = "candidate_watch"
        state = "pace_watch"
        action = "watch_pace_and_recheck"
        reasons.append("pace is slower than reference p75")

    return build_runtime_safety_gate_event(
        gate_id="pace_gate",
        event_id=item.event_id,
        source_provider=item.source_provider,
        source_path=item.source_path,
        observed_at_offset_s=item.observed_at_offset_s,
        state_candidate=state,
        severity=severity,  # type: ignore[arg-type]
        ln_transition_candidate=transition,  # type: ignore[arg-type]
        required_action=action,
        confidence=item.confidence,
        route_pressure_review_required=item.route_pressure_review_required,
        eta_delay_minutes=eta_delay,
        dominant_reasons=reasons,
        evidence_refs=item.evidence_refs,
        route_context=item.route_context,
        data_quality={
            "confidence": item.confidence,
            "signal_count": 3 if item.observed_pace_min_per_km else 2,
            "limitations": [
                "pace gate uses aggregate segment timing only",
                "not a direct cause-of-fatigue diagnosis",
            ],
        },
        gate_payload={
            "observed_segment_minutes": item.observed_segment_minutes,
            "reference_p75_segment_minutes": item.reference_p75_segment_minutes,
            "reference_max_segment_minutes": item.reference_max_segment_minutes,
            "segment_time_ratio": round(ratio, 4),
            "observed_pace_min_per_km": item.observed_pace_min_per_km,
            "reference_p75_pace_min_per_km": item.reference_p75_pace_min_per_km,
            "low_movement_efficiency_ratio": efficiency,
        },
    )


def build_delay_gate_event(
    observation: DelayGateObservation | dict[str, Any],
):
    item = (
        observation
        if isinstance(observation, DelayGateObservation)
        else DelayGateObservation.model_validate(observation)
    )
    negative_buffer = (
        item.planned_buffer_minutes is not None and item.planned_buffer_minutes < 0
    )
    deadline_missed = item.checkpoint_deadline_missed or item.camp_deadline_missed
    delay = item.delay_minutes
    severity = "none"
    transition = "none"
    state = "on_schedule"
    action = "continue_monitoring"
    reasons = [f"delay_minutes:{delay:.1f}"]
    if item.planned_buffer_minutes is not None:
        reasons.append(f"planned_buffer_minutes:{item.planned_buffer_minutes:.1f}")

    if delay >= 60 or deadline_missed or negative_buffer:
        severity = "retreat_review"
        transition = "candidate_retreat"
        state = "timeline_retreat_review"
        action = "review_retreat_hold_or_bivy"
        reasons.append("timeline buffer is exhausted")
    elif delay >= 30:
        severity = "rest"
        transition = "candidate_rest"
        state = "timeline_rest_review"
        action = "pause_plan_and_recompute_eta"
        reasons.append("delay consumes meaningful route buffer")
    elif delay >= 10:
        severity = "watch"
        transition = "candidate_watch"
        state = "timeline_watch"
        action = "watch_delay_and_recheck"
        reasons.append("delay exceeds watch threshold")

    return build_runtime_safety_gate_event(
        gate_id="delay_gate",
        event_id=item.event_id,
        source_provider=item.source_provider,
        source_path=item.source_path,
        observed_at_offset_s=item.observed_at_offset_s,
        state_candidate=state,
        severity=severity,  # type: ignore[arg-type]
        ln_transition_candidate=transition,  # type: ignore[arg-type]
        required_action=action,
        confidence=item.confidence,
        route_pressure_review_required=(
            item.route_pressure_review_required or severity == "retreat_review"
        ),
        eta_delay_minutes=max(0, round(delay)),
        dominant_reasons=reasons,
        evidence_refs=item.evidence_refs,
        route_context=item.route_context,
        data_quality={
            "confidence": item.confidence,
            "signal_count": 2,
            "limitations": ["delay gate does not infer the reason for delay"],
        },
        gate_payload={
            "delay_minutes": delay,
            "planned_buffer_minutes": item.planned_buffer_minutes,
            "checkpoint_deadline_missed": item.checkpoint_deadline_missed,
            "camp_deadline_missed": item.camp_deadline_missed,
        },
    )


def build_darkness_gate_event(
    observation: DarknessGateObservation | dict[str, Any],
):
    item = (
        observation
        if isinstance(observation, DarknessGateObservation)
        else DarknessGateObservation.model_validate(observation)
    )
    margin = item.daylight_buffer_minutes - item.minutes_to_next_safe_objective
    severity = "none"
    transition = "none"
    state = "daylight_buffer_ok"
    action = "continue_monitoring"
    reasons = [
        f"daylight_buffer_minutes:{item.daylight_buffer_minutes:.1f}",
        f"minutes_to_next_safe_objective:{item.minutes_to_next_safe_objective:.1f}",
        f"daylight_margin_minutes:{margin:.1f}",
    ]

    if margin < -30:
        severity = "alert_review"
        transition = "candidate_alert_review"
        state = "darkness_alert_review"
        action = "review_hold_bivy_or_alert"
        reasons.append("next safe objective is beyond daylight buffer")
    elif margin < 0:
        severity = "retreat_review"
        transition = "candidate_retreat"
        state = "darkness_retreat_review"
        action = "review_retreat_or_emergency_bivy"
        reasons.append("daylight buffer is negative")
    elif margin < 30:
        severity = "rest"
        transition = "candidate_rest"
        state = "darkness_rest_review"
        action = "recompute_eta_before_continuing"
        reasons.append("daylight margin is narrow")
    elif margin < 60:
        severity = "watch"
        transition = "candidate_watch"
        state = "darkness_watch"
        action = "watch_daylight_buffer"
        reasons.append("daylight margin is below conservative buffer")

    route_context = item.route_context.model_copy(
        update={"daylight_buffer_minutes": item.daylight_buffer_minutes}
    )
    return build_runtime_safety_gate_event(
        gate_id="darkness_gate",
        event_id=item.event_id,
        source_provider=item.source_provider,
        source_path=item.source_path,
        observed_at_offset_s=item.observed_at_offset_s,
        state_candidate=state,
        severity=severity,  # type: ignore[arg-type]
        ln_transition_candidate=transition,  # type: ignore[arg-type]
        required_action=action,
        confidence=item.confidence,
        route_pressure_review_required=item.route_pressure_review_required,
        eta_delay_minutes=max(0, round(-margin)),
        dominant_reasons=reasons,
        evidence_refs=item.evidence_refs,
        route_context=route_context,
        data_quality={
            "confidence": item.confidence,
            "signal_count": 2,
            "limitations": ["darkness gate uses route-relative daylight margin"],
        },
        gate_payload={
            "daylight_buffer_minutes": item.daylight_buffer_minutes,
            "minutes_to_next_safe_objective": item.minutes_to_next_safe_objective,
            "daylight_margin_minutes": margin,
            "emergency_bivy_candidate_distance_m": (
                item.emergency_bivy_candidate_distance_m
            ),
        },
    )


def build_weather_gate_event(
    observation: WeatherGateObservation | dict[str, Any],
):
    item = (
        observation
        if isinstance(observation, WeatherGateObservation)
        else WeatherGateObservation.model_validate(observation)
    )
    severity_by_level = {
        "none": ("none", "none", "weather_ok", "continue_monitoring"),
        "watch": ("watch", "candidate_watch", "weather_watch", "watch_weather"),
        "advisory": (
            "rest",
            "candidate_rest",
            "weather_rest_review",
            "pause_plan_and_recheck_weather",
        ),
        "unsafe": (
            "retreat_review",
            "candidate_retreat",
            "weather_retreat_review",
            "review_retreat_or_hold",
        ),
        "severe": (
            "alert_review",
            "candidate_alert_review",
            "weather_alert_review",
            "review_alert_hold_or_retreat",
        ),
    }
    severity, transition, state, action = severity_by_level[item.warning_level]
    reasons = [f"warning_level:{item.warning_level}"]
    if item.warning_type:
        reasons.append(f"warning_type:{item.warning_type}")
    for key, enabled in (
        ("wind_risk", item.wind_risk),
        ("rain_risk", item.rain_risk),
        ("lightning_risk", item.lightning_risk),
    ):
        if enabled:
            reasons.append(key)

    missing = []
    stale = []
    if item.source_age_minutes is None:
        missing.append("source_age_minutes")
    elif item.source_age_minutes > 180:
        stale.append("weather_source")

    return build_runtime_safety_gate_event(
        gate_id="weather_gate",
        event_id=item.event_id,
        source_provider=item.source_provider,
        source_path=item.source_path,
        observed_at_offset_s=item.observed_at_offset_s,
        state_candidate=state,
        severity=severity,  # type: ignore[arg-type]
        ln_transition_candidate=transition,  # type: ignore[arg-type]
        required_action=action,
        confidence=item.confidence,
        route_pressure_review_required=(
            item.route_pressure_review_required
            or severity in {"retreat_review", "alert_review"}
        ),
        dominant_reasons=reasons,
        evidence_refs=item.evidence_refs,
        route_context=item.route_context,
        data_quality={
            "confidence": item.confidence,
            "signal_count": 2 + int(item.wind_risk) + int(item.rain_risk),
            "missing_signal_names": missing,
            "stale_signal_names": stale,
            "live_network_calls_made": False,
            "limitations": ["weather gate tests use structured fixture evidence"],
        },
        gate_payload={
            "warning_level": item.warning_level,
            "warning_type": item.warning_type,
            "wind_risk": item.wind_risk,
            "rain_risk": item.rain_risk,
            "lightning_risk": item.lightning_risk,
            "source_age_minutes": item.source_age_minutes,
        },
    )


def build_environment_threat_gate_event(
    observation: EnvironmentThreatGateObservation | dict[str, Any],
):
    item = (
        observation
        if isinstance(observation, EnvironmentThreatGateObservation)
        else EnvironmentThreatGateObservation.model_validate(observation)
    )
    severity = "watch"
    transition = "candidate_watch"
    state = "environment_threat_watch"
    action = "watch_environment_threat"
    reasons = [
        f"threat_type:{item.threat_type}",
        f"passability:{item.passability}",
        f"immediacy:{item.immediacy}",
    ]

    if item.route_blocked or item.passability == "blocked":
        severity = "retreat_review"
        transition = "candidate_retreat"
        state = "environment_route_blocked_review"
        action = "review_retreat_or_safe_bypass"
        reasons.append("route is blocked or no longer passable")
    elif item.immediacy == "immediate" and not item.safe_bypass_known:
        severity = "alert_review"
        transition = "candidate_alert_review"
        state = "environment_immediate_threat_review"
        action = "review_hold_retreat_or_alert"
        reasons.append("immediate threat without known safe bypass")
    elif item.passability == "limited" or item.immediacy == "nearby":
        severity = "rest"
        transition = "candidate_rest"
        state = "environment_rest_review"
        action = "stop_and_review_route"
        reasons.append("field hazard limits route confidence")

    return build_runtime_safety_gate_event(
        gate_id="environment_threat_gate",
        event_id=item.event_id,
        source_provider=item.source_provider,
        source_path=item.source_path,
        observed_at_offset_s=item.observed_at_offset_s,
        state_candidate=state,
        severity=severity,  # type: ignore[arg-type]
        ln_transition_candidate=transition,  # type: ignore[arg-type]
        required_action=action,
        confidence=item.confidence,
        route_pressure_review_required=(
            item.route_pressure_review_required
            or severity in {"retreat_review", "alert_review"}
        ),
        dominant_reasons=reasons,
        evidence_refs=item.evidence_refs,
        route_context=item.route_context,
        data_quality={
            "confidence": item.confidence,
            "signal_count": 2,
            "limitations": [
                "environment threat gate uses structured field report evidence",
            ],
        },
        gate_payload={
            "threat_type": item.threat_type,
            "passability": item.passability,
            "immediacy": item.immediacy,
            "route_blocked": item.route_blocked,
            "safe_bypass_known": item.safe_bypass_known,
        },
    )


def build_production_weather_gate_event(
    observation: ProductionLiveWeatherObservation | dict[str, Any],
):
    item = (
        observation
        if isinstance(observation, ProductionLiveWeatherObservation)
        else ProductionLiveWeatherObservation.model_validate(observation)
    )
    severity, transition, state, action = _weather_state_for_level(item.warning_level)
    reasons = [f"warning_level:{item.warning_level}"]
    if item.warning_type:
        reasons.append(f"warning_type:{item.warning_type}")
    for key, enabled in (
        ("wind_risk", item.wind_risk),
        ("rain_risk", item.rain_risk),
        ("lightning_risk", item.lightning_risk),
    ):
        if enabled:
            reasons.append(key)
    stale = ["weather_source"] if item.source_age_minutes > 180 else []
    source_gate_sha256 = _live_observation_sha256(
        item.model_dump(mode="json"),
        artifact="production_live_weather_observation",
    )
    evidence_refs = _unique_refs(
        [
            item.provider_evidence_ref,
            item.provider_request_ref,
            item.freshness_attestation_ref,
            item.route_scope_ref,
            item.field_attestation_ref,
            *item.evidence_refs,
        ]
    )
    return build_runtime_safety_gate_event(
        gate_id="weather_gate",
        event_id=item.event_id,
        source_provider=item.source_provider,
        source_path=item.source_path,
        source_gate_artifact_kind=item.artifact_kind,
        source_gate_sha256=source_gate_sha256,
        observed_at_offset_s=item.observed_at_offset_s,
        state_candidate=state,
        severity=severity,  # type: ignore[arg-type]
        ln_transition_candidate=transition,  # type: ignore[arg-type]
        required_action=action,
        confidence=item.confidence,
        route_pressure_review_required=(
            item.route_pressure_review_required
            or severity in {"retreat_review", "alert_review"}
        ),
        dominant_reasons=reasons,
        evidence_refs=evidence_refs,
        route_context=item.route_context,
        data_quality={
            "confidence": item.confidence,
            "signal_count": 2
            + int(item.wind_risk)
            + int(item.rain_risk)
            + int(item.lightning_risk),
            "missing_signal_names": [],
            "stale_signal_names": stale,
            "live_network_calls_made": False,
            "limitations": [
                "production live weather bridge consumes sealed refs only",
                "adapter performs no provider network request or runtime ingest",
            ],
        },
        gate_payload={
            "warning_level": item.warning_level,
            "warning_type": item.warning_type,
            "wind_risk": item.wind_risk,
            "rain_risk": item.rain_risk,
            "lightning_risk": item.lightning_risk,
            "source_age_minutes": item.source_age_minutes,
            "provider_dataset_ids": item.provider_dataset_ids,
        },
    )


def build_production_environment_threat_gate_event(
    observation: ProductionLiveEnvironmentThreatObservation | dict[str, Any],
):
    item = (
        observation
        if isinstance(observation, ProductionLiveEnvironmentThreatObservation)
        else ProductionLiveEnvironmentThreatObservation.model_validate(observation)
    )
    severity, transition, state, action, extra_reasons = _threat_state_for_observation(
        passability=item.passability,
        immediacy=item.immediacy,
        route_blocked=item.route_blocked,
        safe_bypass_known=item.safe_bypass_known,
    )
    reasons = [
        f"threat_type:{item.threat_type}",
        f"passability:{item.passability}",
        f"immediacy:{item.immediacy}",
        *extra_reasons,
    ]
    source_gate_sha256 = _live_observation_sha256(
        item.model_dump(mode="json"),
        artifact="production_live_environment_threat_observation",
    )
    evidence_refs = _unique_refs(
        [
            item.current_observation_ref,
            item.provider_request_ref,
            item.freshness_attestation_ref,
            item.route_scope_ref,
            item.provider_evidence_ref,
            item.field_attestation_ref,
            item.device_evidence_ref,
            *item.evidence_refs,
        ]
    )
    return build_runtime_safety_gate_event(
        gate_id="environment_threat_gate",
        event_id=item.event_id,
        source_provider=item.source_provider,
        source_path=item.source_path,
        source_gate_artifact_kind=item.artifact_kind,
        source_gate_sha256=source_gate_sha256,
        observed_at_offset_s=item.observed_at_offset_s,
        state_candidate=state,
        severity=severity,  # type: ignore[arg-type]
        ln_transition_candidate=transition,  # type: ignore[arg-type]
        required_action=action,
        confidence=item.confidence,
        route_pressure_review_required=(
            item.route_pressure_review_required
            or severity in {"retreat_review", "alert_review"}
        ),
        dominant_reasons=reasons,
        evidence_refs=evidence_refs,
        route_context=item.route_context,
        data_quality={
            "confidence": item.confidence,
            "signal_count": 3
            + int(bool(item.provider_evidence_ref))
            + int(bool(item.field_attestation_ref))
            + int(bool(item.device_evidence_ref)),
            "missing_signal_names": [],
            "stale_signal_names": [],
            "live_network_calls_made": False,
            "limitations": [
                "production live threat bridge consumes sealed provider/field/device refs only",
                "adapter performs no provider network request or runtime ingest",
            ],
        },
        gate_payload={
            "threat_type": item.threat_type,
            "passability": item.passability,
            "immediacy": item.immediacy,
            "route_blocked": item.route_blocked,
            "safe_bypass_known": item.safe_bypass_known,
        },
    )


def build_runtime_safety_gate_events_from_live_observations(
    *,
    weather: ProductionLiveWeatherObservation | dict[str, Any] | None = None,
    environment_threat: (
        ProductionLiveEnvironmentThreatObservation | dict[str, Any] | None
    ) = None,
):
    events = []
    if weather is not None:
        events.append(build_production_weather_gate_event(weather))
    if environment_threat is not None:
        events.append(build_production_environment_threat_gate_event(environment_threat))
    return events


def evaluate_production_live_provider_request_contract(
    manifest: ProductionLiveProviderConnectorManifest | dict[str, Any],
    request: ProductionLiveProviderRequestContract | dict[str, Any],
    *,
    source_path: str = "inline:production-live-provider-request-readiness",
) -> ProductionLiveProviderRequestReadinessReceipt:
    manifest_model = (
        manifest
        if isinstance(manifest, ProductionLiveProviderConnectorManifest)
        else ProductionLiveProviderConnectorManifest.model_validate(manifest)
    )
    request_model = (
        request
        if isinstance(request, ProductionLiveProviderRequestContract)
        else ProductionLiveProviderRequestContract.model_validate(request)
    )
    manifest_sha256 = _live_provider_manifest_sha256(manifest_model)
    request_contract_sha256 = _live_provider_request_contract_sha256(
        manifest_sha256=manifest_sha256,
        request=request_model,
    )
    status: ProductionLiveProviderRequestStatus = "dry_run_ready"
    blockers: list[str] = []
    provider_request_ref: str | None = None
    provider_request_sha256: str | None = None

    if _provider_request_lineage_mismatch(manifest_model, request_model):
        status = "blocked_provider_request_lineage_mismatch"
        blockers.append("provider_request_lineage_mismatch")
    elif (
        manifest_model.health_status != "healthy"
        or not manifest_model.connector_health_ref
        or not manifest_model.connector_health_sha256
        or request_model.connector_health_ref != manifest_model.connector_health_ref
        or request_model.connector_health_sha256
        != manifest_model.connector_health_sha256
    ):
        status = "blocked_connector_health_not_ready"
        blockers.append("connector_health_not_ready")
    elif not manifest_model.credential_ref or not request_model.credential_ref:
        status = "blocked_requires_credential_ref"
        blockers.append("credential_ref_missing")
    elif request_model.execution_mode == "provider_effect_boundary_request" and not (
        request_model.reviewed_provider_effect_boundary_ref
        and request_model.reviewed_provider_effect_boundary_sha256
    ):
        status = "blocked_provider_effect_boundary_missing"
        blockers.append("provider_effect_boundary_missing")
    elif request_model.execution_mode == "provider_effect_boundary_request":
        status = "provider_request_boundary_authorized"
        provider_request_sha256 = _live_provider_request_sha256(
            manifest_sha256=manifest_sha256,
            request_contract_sha256=request_contract_sha256,
            request=request_model,
        )
        provider_request_ref = f"provider://request/{provider_request_sha256[:16]}"

    payload = {
        "source_path": source_path,
        "status": status,
        "gate_id": manifest_model.gate_id,
        "connector_id": manifest_model.connector_id,
        "manifest_sha256": manifest_sha256,
        "request_contract_sha256": request_contract_sha256,
        "provider_request_ref": provider_request_ref,
        "provider_request_sha256": provider_request_sha256,
        "blockers": blockers,
    }
    digest = aggregate_sha256([payload])
    return ProductionLiveProviderRequestReadinessReceipt(
        source_path=source_path,
        sha256=digest,
        status=status,
        gate_id=manifest_model.gate_id,
        connector_id=manifest_model.connector_id,
        manifest_sha256=manifest_sha256,
        request_contract_sha256=request_contract_sha256,
        source_observation_path=manifest_model.source_path,
        route_scope_ref=manifest_model.route_scope_ref,
        freshness_requirement_minutes=manifest_model.freshness_requirement_minutes,
        connector_health_ref=manifest_model.connector_health_ref,
        connector_health_sha256=manifest_model.connector_health_sha256,
        credential_ref_present=bool(
            manifest_model.credential_ref and request_model.credential_ref
        ),
        request_contract_prepared=status
        in {"dry_run_ready", "provider_request_boundary_authorized"},
        provider_request_boundary_authorized=(
            status == "provider_request_boundary_authorized"
        ),
        provider_request_ref=provider_request_ref,
        provider_request_sha256=provider_request_sha256,
        execution_mode=request_model.execution_mode,
        blockers=blockers,
        limitations=[
            "local provider request contract only",
            "does not check connector health live, call provider APIs, ingest runtime data, call safety APIs, mutate Phase 1, or expose credential material",
        ],
    )


def build_live_observation_from_provider_response_receipt(
    request_readiness: ProductionLiveProviderRequestReadinessReceipt | dict[str, Any],
    response_receipt: ProductionLiveProviderResponseReceipt | dict[str, Any],
    *,
    provider_executor_invocation: (
        ProductionLiveProviderExecutorInvocationReceipt | dict[str, Any] | None
    ) = None,
    freshness_attestation: ProductionLiveFreshnessAttestationDecision
    | dict[str, Any]
    | None = None,
    field_validation: ProductionLiveFieldDeviceValidationDecision
    | dict[str, Any]
    | None = None,
    source_path: str = "inline:production-live-provider-response-intake",
) -> ProductionLiveProviderResponseIntakeDecision:
    readiness_model = (
        request_readiness
        if isinstance(request_readiness, ProductionLiveProviderRequestReadinessReceipt)
        else ProductionLiveProviderRequestReadinessReceipt.model_validate(
            request_readiness
        )
    )
    receipt_model = (
        response_receipt
        if isinstance(response_receipt, ProductionLiveProviderResponseReceipt)
        else ProductionLiveProviderResponseReceipt.model_validate(response_receipt)
    )
    receipt_sha256 = _live_provider_response_receipt_sha256(receipt_model)
    invocation_model = (
        None
        if provider_executor_invocation is None
        else provider_executor_invocation
        if isinstance(
            provider_executor_invocation,
            ProductionLiveProviderExecutorInvocationReceipt,
        )
        else ProductionLiveProviderExecutorInvocationReceipt.model_validate(
            provider_executor_invocation
        )
    )
    freshness_model = (
        None
        if freshness_attestation is None
        else freshness_attestation
        if isinstance(
            freshness_attestation,
            ProductionLiveFreshnessAttestationDecision,
        )
        else ProductionLiveFreshnessAttestationDecision.model_validate(
            freshness_attestation
        )
    )
    field_validation_model = (
        None
        if field_validation is None
        else field_validation
        if isinstance(field_validation, ProductionLiveFieldDeviceValidationDecision)
        else ProductionLiveFieldDeviceValidationDecision.model_validate(
            field_validation
        )
    )
    request_authorized = (
        readiness_model.status == "provider_request_boundary_authorized"
        and readiness_model.provider_request_boundary_authorized
    )
    lineage_match = _live_provider_response_matches_readiness(
        readiness_model,
        receipt_model,
    )
    invocation_authorized = (
        invocation_model is None
        or (
            invocation_model.status == "provider_executor_invocation_authorized"
            and invocation_model.provider_executor_invocation_authorized
        )
    )
    invocation_lineage_match = (
        invocation_model is None
        or _live_provider_response_matches_invocation(
            invocation_model,
            receipt_model,
        )
    )
    evidence_present = _live_provider_response_evidence_present(receipt_model)
    freshness_evidence_present = bool(
        (receipt_model.freshness_attestation_ref and receipt_model.freshness_attestation_sha256)
        or (
            freshness_model is not None
            and freshness_model.freshness_attestation_prepared
            and freshness_model.freshness_attestation_ref
            and freshness_model.freshness_attestation_sha256
        )
    )
    provider_response_successful = (
        receipt_model.response_status == "success"
        and receipt_model.executor_reported_provider_network_request_performed
        and receipt_model.executor_reported_real_provider_api_called
    )
    freshness_ready = (
        freshness_model is None
        or (
            freshness_model.status == "freshness_attestation_prepared"
            and freshness_model.freshness_attestation_prepared
        )
    )
    freshness_lineage_match = (
        freshness_model is None
        or _live_freshness_attestation_decision_matches_response(
            freshness_model,
            receipt_model,
            receipt_sha256,
        )
    )
    provider_response_current = (
        (
            receipt_model.source_age_minutes
            <= readiness_model.freshness_requirement_minutes
            and receipt_model.freshness_requirement_minutes
            == readiness_model.freshness_requirement_minutes
        )
        if freshness_model is None
        else (
            freshness_model.freshness_attestation_current
            and freshness_model.source_age_minutes
            <= readiness_model.freshness_requirement_minutes
            and freshness_model.freshness_requirement_minutes
            == readiness_model.freshness_requirement_minutes
        )
    )
    field_validation_ready = (
        field_validation_model is None
        or (
            field_validation_model.status == "field_device_validation_prepared"
            and field_validation_model.field_device_validation_prepared
        )
    )
    field_validation_lineage_match = (
        field_validation_model is None
        or _live_field_device_validation_decision_matches_response(
            field_validation_model,
            receipt_model,
            receipt_sha256,
        )
    )
    observation: (
        ProductionLiveWeatherObservation
        | ProductionLiveEnvironmentThreatObservation
        | None
    ) = None
    observation_sha256: str | None = None
    status: ProductionLiveProviderResponseIntakeStatus
    blockers: list[str]

    if not request_authorized:
        status = "blocked_provider_request_not_authorized"
        blockers = ["provider_request_not_authorized"]
    elif not lineage_match:
        status = "blocked_provider_response_lineage_mismatch"
        blockers = ["provider_response_lineage_mismatch"]
    elif not invocation_authorized:
        status = "blocked_provider_executor_invocation_not_authorized"
        blockers = ["provider_executor_invocation_not_authorized"]
    elif not invocation_lineage_match:
        status = "blocked_provider_executor_invocation_lineage_mismatch"
        blockers = ["provider_executor_invocation_lineage_mismatch"]
    elif not evidence_present:
        status = "blocked_missing_provider_evidence"
        blockers = ["provider_evidence_missing"]
    elif not freshness_ready:
        status = "blocked_freshness_attestation_not_ready"
        blockers = ["freshness_attestation_not_ready"]
    elif not freshness_lineage_match:
        status = "blocked_freshness_attestation_lineage_mismatch"
        blockers = ["freshness_attestation_lineage_mismatch"]
    elif not freshness_evidence_present:
        status = "blocked_missing_provider_evidence"
        blockers = ["freshness_evidence_missing"]
    elif not provider_response_successful:
        status = "blocked_provider_response_not_successful"
        blockers = ["provider_response_not_successful"]
    elif not provider_response_current:
        status = "blocked_provider_response_not_current"
        blockers = ["provider_response_not_current"]
    elif not field_validation_ready:
        status = "blocked_field_device_validation_not_ready"
        blockers = ["field_device_validation_not_ready"]
    elif not field_validation_lineage_match:
        status = "blocked_field_device_validation_lineage_mismatch"
        blockers = ["field_device_validation_lineage_mismatch"]
    else:
        status = "live_observation_prepared"
        blockers = []
        observation_receipt = _provider_response_with_attestations(
            receipt_model,
            freshness_model,
            field_validation_model,
        )
        observation = _live_observation_from_provider_response(observation_receipt)
        observation_sha256 = _prepared_live_observation_sha256(observation)

    ready = status == "live_observation_prepared"
    digest = aggregate_sha256(
        [
            {
                "source_path": source_path,
                "request_readiness_sha256": readiness_model.sha256,
                "response_receipt_sha256": receipt_sha256,
                "provider_executor_invocation_sha256": (
                    None if invocation_model is None else invocation_model.sha256
                ),
                "live_observation_sha256": observation_sha256,
                "status": status,
            }
        ]
    )
    return ProductionLiveProviderResponseIntakeDecision(
        source_path=source_path,
        sha256=digest,
        status=status,
        gate_id=readiness_model.gate_id,
        connector_id=readiness_model.connector_id,
        request_readiness_sha256=readiness_model.sha256,
        response_receipt_sha256=receipt_sha256,
        live_observation_sha256=observation_sha256,
        provider_executor_invocation_sha256=(
            None if invocation_model is None else invocation_model.sha256
        ),
        provider_execution_ref=(
            None if invocation_model is None else invocation_model.provider_execution_ref
        ),
        provider_execution_sha256=(
            None
            if invocation_model is None
            else invocation_model.provider_execution_sha256
        ),
        manifest_sha256=readiness_model.manifest_sha256,
        request_contract_sha256=readiness_model.request_contract_sha256,
        source_observation_path=readiness_model.source_observation_path,
        route_scope_ref=readiness_model.route_scope_ref,
        provider_request_ref=readiness_model.provider_request_ref,
        provider_request_sha256=readiness_model.provider_request_sha256,
        provider_evidence_ref=receipt_model.provider_evidence_ref,
        provider_evidence_sha256=receipt_model.provider_evidence_sha256,
        freshness_attestation_ref=(
            freshness_model.freshness_attestation_ref
            if freshness_model is not None
            else receipt_model.freshness_attestation_ref
        ),
        freshness_attestation_sha256=(
            freshness_model.freshness_attestation_sha256
            if freshness_model is not None
            else receipt_model.freshness_attestation_sha256
        ),
        field_device_validation_sha256=(
            None if field_validation_model is None else field_validation_model.sha256
        ),
        field_device_validation_present=(
            field_validation_model is not None
            and field_validation_model.field_device_validation_prepared
        ),
        field_attestation_ref=(
            None if field_validation_model is None else field_validation_model.field_attestation_ref
        ),
        field_attestation_sha256=(
            None
            if field_validation_model is None
            else field_validation_model.field_attestation_sha256
        ),
        device_evidence_ref=(
            None if field_validation_model is None else field_validation_model.device_evidence_ref
        ),
        device_evidence_sha256=(
            None
            if field_validation_model is None
            else field_validation_model.device_evidence_sha256
        ),
        source_age_minutes=receipt_model.source_age_minutes,
        freshness_requirement_minutes=readiness_model.freshness_requirement_minutes,
        provider_response_successful=provider_response_successful,
        provider_response_current=provider_response_current,
        provider_executor_invocation_authorized=(
            invocation_model is not None and invocation_authorized
        ),
        provider_executor_invocation_lineage_match=(
            invocation_model is not None and invocation_lineage_match
        ),
        live_observation_prepared=ready,
        weather_observation=(
            observation
            if isinstance(observation, ProductionLiveWeatherObservation)
            else None
        ),
        environment_threat_observation=(
            observation
            if isinstance(observation, ProductionLiveEnvironmentThreatObservation)
            else None
        ),
        executor_reported_provider_network_request_performed=(
            receipt_model.executor_reported_provider_network_request_performed
        ),
        executor_reported_real_provider_api_called=(
            receipt_model.executor_reported_real_provider_api_called
        ),
        blockers=blockers,
        limitations=[
            "local provider response receipt intake only",
            "does not check connector health live, call provider APIs, ingest runtime data, call safety APIs, mutate Phase 1, or expose credential/raw-location material",
        ],
    )


def evaluate_live_connector_health_executor_invocation_guard(
    invocation_request: (
        ProductionLiveConnectorHealthExecutorInvocationRequest | dict[str, Any]
    ),
    *,
    source_path: str = "inline:production-live-connector-health-invocation",
) -> ProductionLiveConnectorHealthExecutorInvocationReceipt:
    request_model = (
        invocation_request
        if isinstance(
            invocation_request,
            ProductionLiveConnectorHealthExecutorInvocationRequest,
        )
        else ProductionLiveConnectorHealthExecutorInvocationRequest.model_validate(
            invocation_request
        )
    )
    request_sha256 = _live_connector_health_invocation_request_sha256(
        request_model
    )
    boundary_present = bool(
        request_model.reviewed_connector_health_effect_boundary_ref
        and request_model.reviewed_connector_health_effect_boundary_sha256
    )
    fallback_plan_present = bool(
        request_model.fallback_plan_ref and request_model.fallback_plan_sha256
    )
    credential_ref_present = bool(request_model.credential_ref)
    operator_identity_present = bool(
        request_model.operator_identity_ref and request_model.operator_identity_sha256
    )
    explicit_confirmation_present = (
        request_model.explicit_confirmation
        and request_model.confirmation_phrase
        == _CONNECTOR_HEALTH_EXECUTOR_INVOCATION_PHRASE
    )
    status: ProductionLiveConnectorHealthExecutorInvocationStatus
    blockers: list[str]
    connector_health_execution_ref: str | None = None
    connector_health_execution_sha256: str | None = None

    if not boundary_present or not fallback_plan_present:
        status = "blocked_connector_health_effect_boundary_missing"
        blockers = ["connector_health_effect_boundary_missing"]
    elif not credential_ref_present:
        status = "blocked_requires_credential_ref"
        blockers = ["credential_ref_missing"]
    elif not operator_identity_present:
        status = "blocked_connector_health_operator_identity_missing"
        blockers = ["connector_health_operator_identity_missing"]
    elif not explicit_confirmation_present:
        status = "blocked_explicit_connector_health_confirmation_missing"
        blockers = ["explicit_connector_health_confirmation_missing"]
    else:
        status = "connector_health_executor_invocation_authorized"
        blockers = []
        connector_health_execution_ref = (
            "provider://connector-health-execution/"
            f"{request_model.connector_id}/{request_model.idempotency_key}"
        )
        connector_health_execution_sha256 = _live_connector_health_execution_sha256(
            request=request_model,
            invocation_request_sha256=request_sha256,
        )

    digest = aggregate_sha256(
        [
            {
                "source_path": source_path,
                "connector_health_invocation_request_sha256": request_sha256,
                "connector_health_execution_sha256": (
                    connector_health_execution_sha256
                ),
                "status": status,
            }
        ]
    )
    return ProductionLiveConnectorHealthExecutorInvocationReceipt(
        source_path=source_path,
        sha256=digest,
        status=status,
        gate_id=request_model.gate_id,
        connector_id=request_model.connector_id,
        provider_name=request_model.provider_name,
        source_observation_path=request_model.source_path,
        route_scope_ref=request_model.route_scope_ref,
        connector_health_invocation_request_sha256=request_sha256,
        provider_dataset_ids=request_model.provider_dataset_ids,
        reviewed_connector_health_effect_boundary_ref=(
            request_model.reviewed_connector_health_effect_boundary_ref
        ),
        reviewed_connector_health_effect_boundary_sha256=(
            request_model.reviewed_connector_health_effect_boundary_sha256
        ),
        fallback_plan_ref=request_model.fallback_plan_ref,
        fallback_plan_sha256=request_model.fallback_plan_sha256,
        credential_ref=request_model.credential_ref,
        credential_ref_present=credential_ref_present,
        operator_identity_ref=request_model.operator_identity_ref,
        operator_identity_sha256=request_model.operator_identity_sha256,
        operator_role=request_model.operator_role,
        idempotency_key=request_model.idempotency_key,
        connector_health_execution_ref=connector_health_execution_ref,
        connector_health_execution_sha256=connector_health_execution_sha256,
        connector_health_effect_boundary_present=boundary_present,
        fallback_plan_present=fallback_plan_present,
        operator_identity_present=operator_identity_present,
        explicit_confirmation_present=explicit_confirmation_present,
        connector_health_executor_invocation_authorized=(
            status == "connector_health_executor_invocation_authorized"
        ),
        blockers=blockers,
        limitations=[
            "local connector health executor invocation guard only",
            "does not check connector health live, call provider APIs, ingest runtime data, call safety APIs, mutate Phase 1, or expose credential/raw-location material",
        ],
    )


def execute_live_connector_health_check_with_client(
    connector_health_invocation: (
        ProductionLiveConnectorHealthExecutorInvocationReceipt | dict[str, Any]
    ),
    connector_health_client: Callable[
        [ProductionLiveConnectorHealthExecutionRequest],
        ProductionLiveConnectorHealthExecutionResult | dict[str, Any],
    ],
    *,
    source_path: str = "inline:production-live-connector-health-execution",
) -> ProductionLiveConnectorHealthExecutionDecision:
    invocation_model = (
        connector_health_invocation
        if isinstance(
            connector_health_invocation,
            ProductionLiveConnectorHealthExecutorInvocationReceipt,
        )
        else ProductionLiveConnectorHealthExecutorInvocationReceipt.model_validate(
            connector_health_invocation
        )
    )
    invocation_authorized = (
        invocation_model.status == "connector_health_executor_invocation_authorized"
        and invocation_model.connector_health_executor_invocation_authorized
    )
    status: ProductionLiveConnectorHealthExecutionStatus
    blockers: list[str]
    execution_request_sha256: str | None = None
    health_receipt_sha256: str | None = None
    health_receipt: ProductionLiveConnectorHealthReceipt | None = None
    client_called = False
    client_result_valid = False
    client_effect_present = False

    if not invocation_authorized:
        status = "blocked_connector_health_invocation_not_authorized"
        blockers = ["connector_health_invocation_not_authorized"]
    else:
        execution_request = ProductionLiveConnectorHealthExecutionRequest(
            gate_id=invocation_model.gate_id,
            connector_id=invocation_model.connector_id,
            provider_name=invocation_model.provider_name,
            source_observation_path=invocation_model.source_observation_path,
            route_scope_ref=invocation_model.route_scope_ref,
            connector_health_invocation_sha256=invocation_model.sha256,
            connector_health_invocation_request_sha256=(
                invocation_model.connector_health_invocation_request_sha256
            ),
            connector_health_execution_ref=(
                invocation_model.connector_health_execution_ref or ""
            ),
            connector_health_execution_sha256=(
                invocation_model.connector_health_execution_sha256 or ""
            ),
            provider_dataset_ids=invocation_model.provider_dataset_ids,
            reviewed_connector_health_effect_boundary_ref=(
                invocation_model.reviewed_connector_health_effect_boundary_ref or ""
            ),
            reviewed_connector_health_effect_boundary_sha256=(
                invocation_model.reviewed_connector_health_effect_boundary_sha256
                or ""
            ),
            fallback_plan_ref=invocation_model.fallback_plan_ref or "",
            fallback_plan_sha256=invocation_model.fallback_plan_sha256 or "",
            credential_ref=invocation_model.credential_ref or "",
            operator_identity_ref=invocation_model.operator_identity_ref,
            operator_identity_sha256=invocation_model.operator_identity_sha256,
            operator_role=invocation_model.operator_role,
            idempotency_key=invocation_model.idempotency_key,
        )
        execution_request_sha256 = _live_connector_health_execution_request_sha256(
            execution_request
        )
        client_called = True
        try:
            connector_result = connector_health_client(execution_request)
            result_model = (
                connector_result
                if isinstance(
                    connector_result,
                    ProductionLiveConnectorHealthExecutionResult,
                )
                else ProductionLiveConnectorHealthExecutionResult.model_validate(
                    connector_result
                )
            )
        except Exception:  # noqa: BLE001
            status = "blocked_connector_health_client_result_invalid"
            blockers = ["connector_health_client_result_invalid"]
        else:
            client_result_valid = True
            client_effect_present = bool(
                result_model.executor_reported_connector_health_check_performed
                and result_model.executor_reported_provider_network_request_performed
                and result_model.executor_reported_real_provider_api_called
            )
            if (
                result_model.source_path != invocation_model.source_observation_path
                or (
                    result_model.provider_dataset_ids
                    and result_model.provider_dataset_ids
                    != invocation_model.provider_dataset_ids
                )
            ):
                status = "blocked_connector_health_client_result_invalid"
                blockers = ["connector_health_client_result_invalid"]
            elif not client_effect_present:
                status = "blocked_connector_health_client_effect_missing"
                blockers = ["connector_health_client_effect_missing"]
            else:
                try:
                    health_receipt = ProductionLiveConnectorHealthReceipt(
                        source_provider=result_model.source_provider,
                        source_path=invocation_model.source_observation_path,
                        gate_id=invocation_model.gate_id,
                        connector_id=invocation_model.connector_id,
                        provider_name=invocation_model.provider_name,
                        provider_dataset_ids=invocation_model.provider_dataset_ids,
                        route_scope_ref=invocation_model.route_scope_ref,
                        connector_health_invocation_sha256=invocation_model.sha256,
                        connector_health_execution_ref=(
                            invocation_model.connector_health_execution_ref
                        ),
                        connector_health_execution_sha256=(
                            invocation_model.connector_health_execution_sha256
                        ),
                        health_status=result_model.health_status,
                        connector_health_ref=result_model.connector_health_ref,
                        connector_health_sha256=(
                            result_model.connector_health_sha256
                        ),
                        credential_ref=invocation_model.credential_ref,
                        route_scoped_request_supported=(
                            result_model.route_scoped_request_supported
                        ),
                        freshness_attestation_supported=(
                            result_model.freshness_attestation_supported
                        ),
                        effect_boundary_required=(
                            result_model.effect_boundary_required
                        ),
                        executor_reported_connector_health_check_performed=(
                            result_model.executor_reported_connector_health_check_performed
                        ),
                        executor_reported_provider_network_request_performed=(
                            result_model.executor_reported_provider_network_request_performed
                        ),
                        executor_reported_real_provider_api_called=(
                            result_model.executor_reported_real_provider_api_called
                        ),
                    )
                except Exception:  # noqa: BLE001
                    health_receipt = None
                    status = "blocked_connector_health_client_result_invalid"
                    blockers = ["connector_health_client_result_invalid"]
                else:
                    status = "connector_health_receipt_emitted"
                    blockers = []
                    health_receipt_sha256 = _live_connector_health_receipt_sha256(
                        health_receipt
                    )

    digest = aggregate_sha256(
        [
            {
                "source_path": source_path,
                "connector_health_invocation_sha256": invocation_model.sha256,
                "execution_request_sha256": execution_request_sha256,
                "health_receipt_sha256": health_receipt_sha256,
                "status": status,
            }
        ]
    )
    return ProductionLiveConnectorHealthExecutionDecision(
        source_path=source_path,
        sha256=digest,
        status=status,
        gate_id=invocation_model.gate_id,
        connector_id=invocation_model.connector_id,
        provider_name=invocation_model.provider_name,
        source_observation_path=invocation_model.source_observation_path,
        route_scope_ref=invocation_model.route_scope_ref,
        connector_health_invocation_sha256=invocation_model.sha256,
        connector_health_invocation_request_sha256=(
            invocation_model.connector_health_invocation_request_sha256
        ),
        connector_health_execution_ref=invocation_model.connector_health_execution_ref,
        connector_health_execution_sha256=(
            invocation_model.connector_health_execution_sha256
        ),
        execution_request_sha256=execution_request_sha256,
        health_receipt_sha256=health_receipt_sha256,
        health_receipt=health_receipt,
        connector_health_invocation_authorized=invocation_authorized,
        connector_health_client_called=client_called,
        connector_health_client_result_valid=client_result_valid,
        connector_health_client_effect_present=client_effect_present,
        blockers=blockers,
        limitations=[
            "live connector health executor harness requires an injected reviewed health client",
            "tests use fake health clients; no credential value, raw provider payload, runtime ingest, safety API call, Phase 1 mutation, outbound transport, or hardware control is performed by this local verifier",
        ],
    )


def build_live_provider_connector_manifest_from_health_receipt(
    health_receipt: ProductionLiveConnectorHealthReceipt | dict[str, Any],
    *,
    connector_health_invocation: (
        ProductionLiveConnectorHealthExecutorInvocationReceipt | dict[str, Any] | None
    ) = None,
    source_path: str = "inline:production-live-connector-health-intake",
) -> ProductionLiveConnectorHealthIntakeDecision:
    receipt_model = (
        health_receipt
        if isinstance(health_receipt, ProductionLiveConnectorHealthReceipt)
        else ProductionLiveConnectorHealthReceipt.model_validate(health_receipt)
    )
    receipt_sha256 = _live_connector_health_receipt_sha256(receipt_model)
    invocation_model = (
        None
        if connector_health_invocation is None
        else connector_health_invocation
        if isinstance(
            connector_health_invocation,
            ProductionLiveConnectorHealthExecutorInvocationReceipt,
        )
        else ProductionLiveConnectorHealthExecutorInvocationReceipt.model_validate(
            connector_health_invocation
        )
    )
    invocation_authorized = (
        invocation_model is None
        or (
            invocation_model.status
            == "connector_health_executor_invocation_authorized"
            and invocation_model.connector_health_executor_invocation_authorized
        )
    )
    invocation_lineage_match = (
        invocation_model is None
        or _live_connector_health_receipt_matches_invocation(
            invocation_model,
            receipt_model,
        )
    )
    health_check_performed = (
        receipt_model.executor_reported_connector_health_check_performed
    )
    health_evidence_present = bool(
        receipt_model.connector_health_ref and receipt_model.connector_health_sha256
    )
    connector_healthy = receipt_model.health_status == "healthy"
    credential_ref_present = bool(receipt_model.credential_ref)
    manifest: ProductionLiveProviderConnectorManifest | None = None
    manifest_sha256: str | None = None
    status: ProductionLiveConnectorHealthIntakeStatus
    blockers: list[str]

    if not invocation_authorized:
        status = "blocked_connector_health_invocation_not_authorized"
        blockers = ["connector_health_invocation_not_authorized"]
    elif not invocation_lineage_match:
        status = "blocked_connector_health_invocation_lineage_mismatch"
        blockers = ["connector_health_invocation_lineage_mismatch"]
    elif not health_check_performed:
        status = "blocked_connector_health_check_missing"
        blockers = ["connector_health_check_missing"]
    elif not health_evidence_present:
        status = "blocked_connector_health_evidence_missing"
        blockers = ["connector_health_evidence_missing"]
    elif not connector_healthy:
        status = "blocked_connector_health_not_ready"
        blockers = ["connector_health_not_ready"]
    elif not credential_ref_present:
        status = "blocked_requires_credential_ref"
        blockers = ["credential_ref_missing"]
    else:
        status = "connector_manifest_prepared"
        blockers = []
        manifest = ProductionLiveProviderConnectorManifest(
            gate_id=receipt_model.gate_id,
            connector_id=receipt_model.connector_id,
            provider_name=receipt_model.provider_name,
            source_provider=receipt_model.source_provider,
            source_path=receipt_model.source_path,
            provider_dataset_ids=receipt_model.provider_dataset_ids,
            route_scope_ref=receipt_model.route_scope_ref,
            health_status=receipt_model.health_status,
            connector_health_ref=receipt_model.connector_health_ref,
            connector_health_sha256=receipt_model.connector_health_sha256,
            credential_ref=receipt_model.credential_ref,
            freshness_requirement_minutes=(
                receipt_model.freshness_requirement_minutes
            ),
            route_scoped_request_supported=(
                receipt_model.route_scoped_request_supported
            ),
            freshness_attestation_supported=(
                receipt_model.freshness_attestation_supported
            ),
            effect_boundary_required=receipt_model.effect_boundary_required,
        )
        manifest_sha256 = _live_provider_manifest_sha256(manifest)

    digest = aggregate_sha256(
        [
            {
                "source_path": source_path,
                "health_receipt_sha256": receipt_sha256,
                "connector_health_invocation_sha256": (
                    None if invocation_model is None else invocation_model.sha256
                ),
                "connector_manifest_sha256": manifest_sha256,
                "status": status,
            }
        ]
    )
    return ProductionLiveConnectorHealthIntakeDecision(
        source_path=source_path,
        sha256=digest,
        status=status,
        gate_id=receipt_model.gate_id,
        connector_id=receipt_model.connector_id,
        health_receipt_sha256=receipt_sha256,
        connector_manifest_sha256=manifest_sha256,
        source_observation_path=receipt_model.source_path,
        route_scope_ref=receipt_model.route_scope_ref,
        connector_health_invocation_sha256=(
            None if invocation_model is None else invocation_model.sha256
        ),
        connector_health_execution_ref=receipt_model.connector_health_execution_ref,
        connector_health_execution_sha256=(
            receipt_model.connector_health_execution_sha256
        ),
        health_status=receipt_model.health_status,
        connector_health_ref=receipt_model.connector_health_ref,
        connector_health_sha256=receipt_model.connector_health_sha256,
        credential_ref_present=credential_ref_present,
        connector_health_invocation_authorized=(
            invocation_model is not None and invocation_authorized
        ),
        connector_health_invocation_lineage_match=(
            invocation_model is not None and invocation_lineage_match
        ),
        connector_health_check_performed=health_check_performed,
        connector_health_evidence_present=health_evidence_present,
        connector_healthy=connector_healthy,
        connector_manifest_prepared=status == "connector_manifest_prepared",
        connector_manifest=manifest,
        executor_reported_provider_network_request_performed=(
            receipt_model.executor_reported_provider_network_request_performed
        ),
        executor_reported_real_provider_api_called=(
            receipt_model.executor_reported_real_provider_api_called
        ),
        blockers=blockers,
        limitations=[
            "local connector health receipt intake only",
            "does not perform live health checks, call provider APIs, ingest runtime data, call safety APIs, mutate Phase 1, or expose credential/raw-location material",
        ],
    )


def build_live_field_device_validation_intake(
    validation_receipt: ProductionLiveFieldDeviceValidationReceipt | dict[str, Any],
    provider_response_receipt: (
        ProductionLiveProviderResponseReceipt | dict[str, Any] | None
    ) = None,
    *,
    field_device_validator_invocation: (
        ProductionLiveFieldDeviceValidatorInvocationReceipt | dict[str, Any] | None
    ) = None,
    source_path: str = "inline:production-live-field-device-validation-intake",
) -> ProductionLiveFieldDeviceValidationDecision:
    receipt_model = (
        validation_receipt
        if isinstance(validation_receipt, ProductionLiveFieldDeviceValidationReceipt)
        else ProductionLiveFieldDeviceValidationReceipt.model_validate(
            validation_receipt
        )
    )
    response_model = (
        None
        if provider_response_receipt is None
        else provider_response_receipt
        if isinstance(provider_response_receipt, ProductionLiveProviderResponseReceipt)
        else ProductionLiveProviderResponseReceipt.model_validate(
            provider_response_receipt
        )
    )
    invocation_model = (
        None
        if field_device_validator_invocation is None
        else field_device_validator_invocation
        if isinstance(
            field_device_validator_invocation,
            ProductionLiveFieldDeviceValidatorInvocationReceipt,
        )
        else ProductionLiveFieldDeviceValidatorInvocationReceipt.model_validate(
            field_device_validator_invocation
        )
    )
    validation_sha256 = _live_field_device_validation_receipt_sha256(receipt_model)
    response_sha256 = (
        None
        if response_model is None
        else _live_provider_response_receipt_sha256(response_model)
    )
    invocation_sha256 = None if invocation_model is None else invocation_model.sha256
    invocation_authorized = (
        invocation_model is None
        or (
            invocation_model.status == "field_device_validator_invocation_authorized"
            and invocation_model.field_device_validator_invocation_authorized
        )
    )
    invocation_lineage_match = (
        invocation_model is None
        or _live_field_device_validation_matches_invocation(
            invocation_model,
            receipt_model,
        )
    )
    lineage_match = response_model is None or _live_field_device_validation_matches_response(
        receipt_model,
        response_model,
        response_sha256 or "",
    )
    validation_performed = (
        receipt_model.executor_reported_field_device_validation_performed
    )
    evidence_present = bool(
        receipt_model.field_attestation_ref
        and receipt_model.field_attestation_sha256
        and (
            receipt_model.current_observation_ref
            or (
                receipt_model.device_evidence_ref
                and receipt_model.device_evidence_sha256
            )
        )
    )
    confirmed = receipt_model.validation_status == "confirmed"
    current = receipt_model.validation_age_minutes <= receipt_model.max_validation_age_minutes
    status: ProductionLiveFieldDeviceValidationIntakeStatus
    blockers: list[str]

    if not invocation_authorized:
        status = "blocked_field_device_validator_invocation_not_authorized"
        blockers = ["field_device_validator_invocation_not_authorized"]
    elif not invocation_lineage_match:
        status = "blocked_field_device_validator_invocation_lineage_mismatch"
        blockers = ["field_device_validator_invocation_lineage_mismatch"]
    elif not lineage_match:
        status = "blocked_field_device_validation_lineage_mismatch"
        blockers = ["field_device_validation_lineage_mismatch"]
    elif not (validation_performed and evidence_present):
        status = "blocked_field_device_validation_evidence_missing"
        blockers = ["field_device_validation_evidence_missing"]
    elif not confirmed:
        status = "blocked_field_device_validation_not_confirmed"
        blockers = ["field_device_validation_not_confirmed"]
    elif not current:
        status = "blocked_field_device_validation_not_current"
        blockers = ["field_device_validation_not_current"]
    else:
        status = "field_device_validation_prepared"
        blockers = []

    digest = aggregate_sha256(
        [
            {
                "source_path": source_path,
                "validation_receipt_sha256": validation_sha256,
                "provider_response_receipt_sha256": response_sha256,
                "field_device_validator_invocation_sha256": invocation_sha256,
                "status": status,
            }
        ]
    )
    return ProductionLiveFieldDeviceValidationDecision(
        source_path=source_path,
        sha256=digest,
        status=status,
        gate_id=receipt_model.gate_id,
        validation_receipt_sha256=validation_sha256,
        provider_response_receipt_sha256=response_sha256,
        source_observation_path=receipt_model.source_observation_path,
        route_scope_ref=receipt_model.route_scope_ref,
        provider_request_ref=receipt_model.provider_request_ref,
        field_device_validator_invocation_sha256=(
            receipt_model.field_device_validator_invocation_sha256
        ),
        field_device_validation_execution_ref=(
            receipt_model.field_device_validation_execution_ref
        ),
        field_device_validation_execution_sha256=(
            receipt_model.field_device_validation_execution_sha256
        ),
        current_observation_ref=receipt_model.current_observation_ref,
        field_attestation_ref=receipt_model.field_attestation_ref,
        field_attestation_sha256=receipt_model.field_attestation_sha256,
        device_evidence_ref=receipt_model.device_evidence_ref,
        device_evidence_sha256=receipt_model.device_evidence_sha256,
        operator_review_ref=receipt_model.operator_review_ref,
        operator_review_sha256=receipt_model.operator_review_sha256,
        validation_status=receipt_model.validation_status,
        validation_age_minutes=receipt_model.validation_age_minutes,
        max_validation_age_minutes=receipt_model.max_validation_age_minutes,
        field_device_validation_performed=validation_performed,
        field_device_validation_evidence_present=evidence_present,
        field_device_validation_confirmed=confirmed,
        field_device_validation_current=current,
        field_device_validation_prepared=(
            status == "field_device_validation_prepared"
        ),
        field_device_validator_invocation_authorized=(
            invocation_model is not None and invocation_authorized
        ),
        field_device_validator_invocation_lineage_match=(
            invocation_model is not None and invocation_lineage_match
        ),
        blockers=blockers,
        limitations=[
            "local field/device validation receipt intake only",
            "does not perform field validation, call provider APIs, ingest runtime data, call safety APIs, mutate Phase 1, or expose credential/raw-location material",
        ],
    )


def evaluate_live_field_device_validator_invocation_guard(
    invocation_request: (
        ProductionLiveFieldDeviceValidatorInvocationRequest | dict[str, Any]
    ),
    *,
    source_path: str = "inline:production-live-field-device-validator-invocation",
) -> ProductionLiveFieldDeviceValidatorInvocationReceipt:
    request_model = (
        invocation_request
        if isinstance(
            invocation_request,
            ProductionLiveFieldDeviceValidatorInvocationRequest,
        )
        else ProductionLiveFieldDeviceValidatorInvocationRequest.model_validate(
            invocation_request
        )
    )
    request_sha256 = _live_field_device_validator_invocation_request_sha256(
        request_model
    )
    boundary_present = bool(
        request_model.reviewed_field_device_validator_effect_boundary_ref
        and request_model.reviewed_field_device_validator_effect_boundary_sha256
    )
    input_evidence_present = bool(
        request_model.current_observation_ref
        or (request_model.device_evidence_ref and request_model.device_evidence_sha256)
    )
    fallback_plan_present = bool(
        request_model.fallback_plan_ref and request_model.fallback_plan_sha256
    )
    operator_identity_present = bool(
        request_model.operator_identity_ref and request_model.operator_identity_sha256
    )
    explicit_confirmation_present = (
        request_model.explicit_confirmation
        and request_model.confirmation_phrase
        == _FIELD_DEVICE_VALIDATOR_INVOCATION_PHRASE
    )
    status: ProductionLiveFieldDeviceValidatorInvocationStatus
    blockers: list[str]
    field_device_execution_ref: str | None = None
    field_device_execution_sha256: str | None = None

    if not boundary_present or not fallback_plan_present:
        status = "blocked_field_device_validator_effect_boundary_missing"
        blockers = ["field_device_validator_effect_boundary_missing"]
    elif not input_evidence_present:
        status = "blocked_field_device_validator_input_evidence_missing"
        blockers = ["field_device_validator_input_evidence_missing"]
    elif not operator_identity_present:
        status = "blocked_field_device_validator_operator_identity_missing"
        blockers = ["field_device_validator_operator_identity_missing"]
    elif not explicit_confirmation_present:
        status = "blocked_explicit_field_device_validator_confirmation_missing"
        blockers = ["explicit_field_device_validator_confirmation_missing"]
    else:
        status = "field_device_validator_invocation_authorized"
        blockers = []
        field_device_execution_ref = (
            "attestation://field-device-validation-execution/"
            f"{request_model.gate_id}/{request_model.idempotency_key}"
        )
        field_device_execution_sha256 = (
            _live_field_device_validator_execution_sha256(
                request=request_model,
                invocation_request_sha256=request_sha256,
            )
        )

    digest = aggregate_sha256(
        [
            {
                "source_path": source_path,
                "field_device_validator_invocation_request_sha256": (
                    request_sha256
                ),
                "field_device_validation_execution_sha256": (
                    field_device_execution_sha256
                ),
                "status": status,
            }
        ]
    )
    return ProductionLiveFieldDeviceValidatorInvocationReceipt(
        source_path=source_path,
        sha256=digest,
        status=status,
        gate_id=request_model.gate_id,
        field_device_validator_invocation_request_sha256=request_sha256,
        source_observation_path=request_model.source_observation_path,
        route_scope_ref=request_model.route_scope_ref,
        provider_request_ref=request_model.provider_request_ref,
        provider_response_receipt_sha256=(
            request_model.provider_response_receipt_sha256
        ),
        current_observation_ref=request_model.current_observation_ref,
        device_evidence_ref=request_model.device_evidence_ref,
        device_evidence_sha256=request_model.device_evidence_sha256,
        reviewed_field_device_validator_effect_boundary_ref=(
            request_model.reviewed_field_device_validator_effect_boundary_ref
        ),
        reviewed_field_device_validator_effect_boundary_sha256=(
            request_model.reviewed_field_device_validator_effect_boundary_sha256
        ),
        fallback_plan_ref=request_model.fallback_plan_ref,
        fallback_plan_sha256=request_model.fallback_plan_sha256,
        operator_identity_ref=request_model.operator_identity_ref,
        operator_identity_sha256=request_model.operator_identity_sha256,
        operator_role=request_model.operator_role,
        idempotency_key=request_model.idempotency_key,
        field_device_validation_execution_ref=field_device_execution_ref,
        field_device_validation_execution_sha256=field_device_execution_sha256,
        field_device_validator_effect_boundary_present=boundary_present,
        field_device_validator_input_evidence_present=input_evidence_present,
        fallback_plan_present=fallback_plan_present,
        operator_identity_present=operator_identity_present,
        explicit_confirmation_present=explicit_confirmation_present,
        field_device_validator_invocation_authorized=(
            status == "field_device_validator_invocation_authorized"
        ),
        blockers=blockers,
        limitations=[
            "local field/device validator invocation guard only",
            "does not perform field validation, call provider APIs, ingest runtime data, call safety APIs, mutate Phase 1, or expose credential/raw-location material",
        ],
    )


def execute_live_field_device_validation_with_client(
    field_device_validator_invocation: (
        ProductionLiveFieldDeviceValidatorInvocationReceipt | dict[str, Any]
    ),
    field_device_validation_client: Callable[
        [ProductionLiveFieldDeviceValidationExecutionRequest],
        ProductionLiveFieldDeviceValidationExecutionResult | dict[str, Any],
    ],
    *,
    source_path: str = "inline:production-live-field-device-validation-execution",
) -> ProductionLiveFieldDeviceValidationExecutionDecision:
    invocation_model = (
        field_device_validator_invocation
        if isinstance(
            field_device_validator_invocation,
            ProductionLiveFieldDeviceValidatorInvocationReceipt,
        )
        else ProductionLiveFieldDeviceValidatorInvocationReceipt.model_validate(
            field_device_validator_invocation
        )
    )
    invocation_authorized = (
        invocation_model.status == "field_device_validator_invocation_authorized"
        and invocation_model.field_device_validator_invocation_authorized
    )
    status: ProductionLiveFieldDeviceValidationExecutionStatus
    blockers: list[str]
    execution_request_sha256: str | None = None
    validation_receipt_sha256: str | None = None
    validation_receipt: ProductionLiveFieldDeviceValidationReceipt | None = None
    client_called = False
    client_result_valid = False
    client_effect_present = False

    if not invocation_authorized:
        status = "blocked_field_device_validator_invocation_not_authorized"
        blockers = ["field_device_validator_invocation_not_authorized"]
    else:
        execution_request = ProductionLiveFieldDeviceValidationExecutionRequest(
            gate_id=invocation_model.gate_id,
            field_device_validator_invocation_sha256=invocation_model.sha256,
            field_device_validator_invocation_request_sha256=(
                invocation_model.field_device_validator_invocation_request_sha256
            ),
            source_observation_path=invocation_model.source_observation_path,
            route_scope_ref=invocation_model.route_scope_ref,
            provider_request_ref=invocation_model.provider_request_ref,
            provider_response_receipt_sha256=(
                invocation_model.provider_response_receipt_sha256
            ),
            current_observation_ref=invocation_model.current_observation_ref,
            device_evidence_ref=invocation_model.device_evidence_ref,
            device_evidence_sha256=invocation_model.device_evidence_sha256,
            field_device_validation_execution_ref=(
                invocation_model.field_device_validation_execution_ref or ""
            ),
            field_device_validation_execution_sha256=(
                invocation_model.field_device_validation_execution_sha256 or ""
            ),
            reviewed_field_device_validator_effect_boundary_ref=(
                invocation_model.reviewed_field_device_validator_effect_boundary_ref
                or ""
            ),
            reviewed_field_device_validator_effect_boundary_sha256=(
                invocation_model.reviewed_field_device_validator_effect_boundary_sha256
                or ""
            ),
            fallback_plan_ref=invocation_model.fallback_plan_ref or "",
            fallback_plan_sha256=invocation_model.fallback_plan_sha256 or "",
            operator_identity_ref=invocation_model.operator_identity_ref,
            operator_identity_sha256=invocation_model.operator_identity_sha256,
            operator_role=invocation_model.operator_role,
            idempotency_key=invocation_model.idempotency_key,
        )
        execution_request_sha256 = (
            _live_field_device_validation_execution_request_sha256(
                execution_request
            )
        )
        client_called = True
        try:
            client_result = field_device_validation_client(execution_request)
            result_model = (
                client_result
                if isinstance(
                    client_result,
                    ProductionLiveFieldDeviceValidationExecutionResult,
                )
                else ProductionLiveFieldDeviceValidationExecutionResult.model_validate(
                    client_result
                )
            )
        except Exception:  # noqa: BLE001
            status = "blocked_field_device_client_result_invalid"
            blockers = ["field_device_client_result_invalid"]
        else:
            client_result_valid = True
            client_effect_present = bool(
                result_model.executor_reported_field_device_validation_performed
                and result_model.field_attestation_ref
                and result_model.field_attestation_sha256
                and (
                    result_model.current_observation_ref
                    or (
                        result_model.device_evidence_ref
                        and result_model.device_evidence_sha256
                    )
                )
            )
            lineage_match = (
                result_model.gate_id == invocation_model.gate_id
                and result_model.route_scope_ref == invocation_model.route_scope_ref
                and result_model.source_observation_path
                == invocation_model.source_observation_path
                and result_model.provider_request_ref
                == invocation_model.provider_request_ref
                and result_model.provider_response_receipt_sha256
                == invocation_model.provider_response_receipt_sha256
                and (
                    invocation_model.current_observation_ref is None
                    or result_model.current_observation_ref
                    == invocation_model.current_observation_ref
                )
                and (
                    invocation_model.device_evidence_ref is None
                    or result_model.device_evidence_ref
                    == invocation_model.device_evidence_ref
                )
                and (
                    invocation_model.device_evidence_sha256 is None
                    or result_model.device_evidence_sha256
                    == invocation_model.device_evidence_sha256
                )
            )
            if not lineage_match:
                status = "blocked_field_device_client_result_invalid"
                blockers = ["field_device_client_result_invalid"]
            elif not client_effect_present:
                status = "blocked_field_device_client_effect_missing"
                blockers = ["field_device_client_effect_missing"]
            else:
                try:
                    validation_receipt = ProductionLiveFieldDeviceValidationReceipt(
                        source_provider=result_model.source_provider,
                        source_path=result_model.source_path,
                        gate_id=invocation_model.gate_id,
                        source_observation_path=(
                            invocation_model.source_observation_path
                        ),
                        route_scope_ref=invocation_model.route_scope_ref,
                        provider_request_ref=invocation_model.provider_request_ref,
                        provider_response_receipt_sha256=(
                            invocation_model.provider_response_receipt_sha256
                        ),
                        field_device_validator_invocation_sha256=(
                            invocation_model.sha256
                        ),
                        field_device_validation_execution_ref=(
                            invocation_model.field_device_validation_execution_ref
                        ),
                        field_device_validation_execution_sha256=(
                            invocation_model.field_device_validation_execution_sha256
                        ),
                        current_observation_ref=(
                            result_model.current_observation_ref
                        ),
                        field_attestation_ref=result_model.field_attestation_ref,
                        field_attestation_sha256=(
                            result_model.field_attestation_sha256
                        ),
                        device_evidence_ref=result_model.device_evidence_ref,
                        device_evidence_sha256=result_model.device_evidence_sha256,
                        operator_review_ref=result_model.operator_review_ref,
                        operator_review_sha256=result_model.operator_review_sha256,
                        validation_status=result_model.validation_status,
                        validation_age_minutes=result_model.validation_age_minutes,
                        max_validation_age_minutes=(
                            result_model.max_validation_age_minutes
                        ),
                        route_context=result_model.route_context,
                        confidence=result_model.confidence,
                        executor_reported_field_device_validation_performed=(
                            result_model.executor_reported_field_device_validation_performed
                        ),
                    )
                except Exception:  # noqa: BLE001
                    validation_receipt = None
                    status = "blocked_field_device_client_result_invalid"
                    blockers = ["field_device_client_result_invalid"]
                else:
                    status = "field_device_validation_receipt_emitted"
                    blockers = []
                    validation_receipt_sha256 = (
                        _live_field_device_validation_receipt_sha256(
                            validation_receipt
                        )
                    )

    digest = aggregate_sha256(
        [
            {
                "source_path": source_path,
                "field_device_validator_invocation_sha256": invocation_model.sha256,
                "execution_request_sha256": execution_request_sha256,
                "validation_receipt_sha256": validation_receipt_sha256,
                "status": status,
            }
        ]
    )
    return ProductionLiveFieldDeviceValidationExecutionDecision(
        source_path=source_path,
        sha256=digest,
        status=status,
        gate_id=invocation_model.gate_id,
        field_device_validator_invocation_sha256=invocation_model.sha256,
        field_device_validation_execution_ref=(
            invocation_model.field_device_validation_execution_ref
        ),
        field_device_validation_execution_sha256=(
            invocation_model.field_device_validation_execution_sha256
        ),
        execution_request_sha256=execution_request_sha256,
        validation_receipt_sha256=validation_receipt_sha256,
        validation_receipt=validation_receipt,
        field_device_validator_invocation_authorized=invocation_authorized,
        field_device_validation_client_called=client_called,
        field_device_validation_client_result_valid=client_result_valid,
        field_device_validation_client_effect_present=client_effect_present,
        blockers=blockers,
        limitations=[
            "local injected field/device validation client harness only",
            "does not call provider APIs, ingest runtime data, call safety APIs, mutate Phase 1, invoke transport, control hardware, or expose credential/raw-location material",
        ],
    )


def evaluate_live_freshness_attestor_invocation_guard(
    invocation_request: (
        ProductionLiveFreshnessAttestorInvocationRequest | dict[str, Any]
    ),
    *,
    source_path: str = "inline:production-live-freshness-attestor-invocation",
) -> ProductionLiveFreshnessAttestorInvocationReceipt:
    request_model = (
        invocation_request
        if isinstance(
            invocation_request,
            ProductionLiveFreshnessAttestorInvocationRequest,
        )
        else ProductionLiveFreshnessAttestorInvocationRequest.model_validate(
            invocation_request
        )
    )
    request_sha256 = _live_freshness_attestor_invocation_request_sha256(
        request_model
    )
    boundary_present = bool(
        request_model.reviewed_freshness_attestor_effect_boundary_ref
        and request_model.reviewed_freshness_attestor_effect_boundary_sha256
    )
    input_evidence_present = bool(
        request_model.provider_evidence_ref
        and request_model.provider_evidence_sha256
    )
    fallback_plan_present = bool(
        request_model.fallback_plan_ref and request_model.fallback_plan_sha256
    )
    operator_identity_present = bool(
        request_model.operator_identity_ref and request_model.operator_identity_sha256
    )
    explicit_confirmation_present = (
        request_model.explicit_confirmation
        and request_model.confirmation_phrase
        == _FRESHNESS_ATTESTOR_INVOCATION_PHRASE
    )
    status: ProductionLiveFreshnessAttestorInvocationStatus
    blockers: list[str]
    freshness_execution_ref: str | None = None
    freshness_execution_sha256: str | None = None

    if not boundary_present or not fallback_plan_present:
        status = "blocked_freshness_attestor_effect_boundary_missing"
        blockers = ["freshness_attestor_effect_boundary_missing"]
    elif not input_evidence_present:
        status = "blocked_freshness_attestor_input_evidence_missing"
        blockers = ["freshness_attestor_input_evidence_missing"]
    elif not operator_identity_present:
        status = "blocked_freshness_attestor_operator_identity_missing"
        blockers = ["freshness_attestor_operator_identity_missing"]
    elif not explicit_confirmation_present:
        status = "blocked_explicit_freshness_attestor_confirmation_missing"
        blockers = ["explicit_freshness_attestor_confirmation_missing"]
    else:
        status = "freshness_attestor_invocation_authorized"
        blockers = []
        freshness_execution_ref = (
            "attestation://freshness-execution/"
            f"{request_model.gate_id}/{request_model.idempotency_key}"
        )
        freshness_execution_sha256 = _live_freshness_attestor_execution_sha256(
            request=request_model,
            invocation_request_sha256=request_sha256,
        )

    digest = aggregate_sha256(
        [
            {
                "source_path": source_path,
                "freshness_attestor_invocation_request_sha256": request_sha256,
                "freshness_attestation_execution_sha256": (
                    freshness_execution_sha256
                ),
                "status": status,
            }
        ]
    )
    return ProductionLiveFreshnessAttestorInvocationReceipt(
        source_path=source_path,
        sha256=digest,
        status=status,
        gate_id=request_model.gate_id,
        freshness_attestor_invocation_request_sha256=request_sha256,
        source_observation_path=request_model.source_observation_path,
        route_scope_ref=request_model.route_scope_ref,
        provider_request_ref=request_model.provider_request_ref,
        provider_response_receipt_sha256=(
            request_model.provider_response_receipt_sha256
        ),
        provider_evidence_ref=request_model.provider_evidence_ref,
        provider_evidence_sha256=request_model.provider_evidence_sha256,
        freshness_requirement_minutes=request_model.freshness_requirement_minutes,
        reviewed_freshness_attestor_effect_boundary_ref=(
            request_model.reviewed_freshness_attestor_effect_boundary_ref
        ),
        reviewed_freshness_attestor_effect_boundary_sha256=(
            request_model.reviewed_freshness_attestor_effect_boundary_sha256
        ),
        fallback_plan_ref=request_model.fallback_plan_ref,
        fallback_plan_sha256=request_model.fallback_plan_sha256,
        operator_identity_ref=request_model.operator_identity_ref,
        operator_identity_sha256=request_model.operator_identity_sha256,
        operator_role=request_model.operator_role,
        idempotency_key=request_model.idempotency_key,
        freshness_attestation_execution_ref=freshness_execution_ref,
        freshness_attestation_execution_sha256=freshness_execution_sha256,
        freshness_attestor_effect_boundary_present=boundary_present,
        freshness_attestor_input_evidence_present=input_evidence_present,
        fallback_plan_present=fallback_plan_present,
        operator_identity_present=operator_identity_present,
        explicit_confirmation_present=explicit_confirmation_present,
        freshness_attestor_invocation_authorized=(
            status == "freshness_attestor_invocation_authorized"
        ),
        blockers=blockers,
        limitations=[
            "local freshness attestor invocation guard only",
            "does not perform freshness checks, call provider APIs, ingest runtime data, call safety APIs, mutate Phase 1, or expose credential/raw-location material",
        ],
    )


def build_live_freshness_attestation_intake(
    freshness_receipt: ProductionLiveFreshnessAttestationReceipt | dict[str, Any],
    provider_response_receipt: (
        ProductionLiveProviderResponseReceipt | dict[str, Any] | None
    ) = None,
    *,
    freshness_attestor_invocation: (
        ProductionLiveFreshnessAttestorInvocationReceipt | dict[str, Any] | None
    ) = None,
    source_path: str = "inline:production-live-freshness-attestation-intake",
) -> ProductionLiveFreshnessAttestationDecision:
    receipt_model = (
        freshness_receipt
        if isinstance(freshness_receipt, ProductionLiveFreshnessAttestationReceipt)
        else ProductionLiveFreshnessAttestationReceipt.model_validate(
            freshness_receipt
        )
    )
    response_model = (
        None
        if provider_response_receipt is None
        else provider_response_receipt
        if isinstance(provider_response_receipt, ProductionLiveProviderResponseReceipt)
        else ProductionLiveProviderResponseReceipt.model_validate(
            provider_response_receipt
        )
    )
    freshness_sha256 = _live_freshness_attestation_receipt_sha256(receipt_model)
    response_sha256 = (
        None
        if response_model is None
        else _live_provider_response_receipt_sha256(response_model)
    )
    invocation_model = (
        None
        if freshness_attestor_invocation is None
        else freshness_attestor_invocation
        if isinstance(
            freshness_attestor_invocation,
            ProductionLiveFreshnessAttestorInvocationReceipt,
        )
        else ProductionLiveFreshnessAttestorInvocationReceipt.model_validate(
            freshness_attestor_invocation
        )
    )
    invocation_authorized = (
        invocation_model is None
        or (
            invocation_model.status == "freshness_attestor_invocation_authorized"
            and invocation_model.freshness_attestor_invocation_authorized
        )
    )
    invocation_lineage_match = (
        invocation_model is None
        or _live_freshness_attestation_matches_invocation(
            invocation_model,
            receipt_model,
        )
    )
    lineage_match = response_model is None or _live_freshness_attestation_matches_response(
        receipt_model,
        response_model,
        response_sha256 or "",
    )
    freshness_check_performed = (
        receipt_model.executor_reported_freshness_check_performed
    )
    evidence_present = bool(
        receipt_model.freshness_attestation_ref
        and receipt_model.freshness_attestation_sha256
        and receipt_model.provider_evidence_ref
        and receipt_model.provider_evidence_sha256
    )
    current = (
        receipt_model.freshness_status == "current"
        and receipt_model.attested_current
        and receipt_model.source_age_minutes
        <= receipt_model.freshness_requirement_minutes
    )
    status: ProductionLiveFreshnessAttestationIntakeStatus
    blockers: list[str]

    if not invocation_authorized:
        status = "blocked_freshness_attestor_invocation_not_authorized"
        blockers = ["freshness_attestor_invocation_not_authorized"]
    elif not invocation_lineage_match:
        status = "blocked_freshness_attestor_invocation_lineage_mismatch"
        blockers = ["freshness_attestor_invocation_lineage_mismatch"]
    elif not lineage_match:
        status = "blocked_freshness_attestation_lineage_mismatch"
        blockers = ["freshness_attestation_lineage_mismatch"]
    elif not (freshness_check_performed and evidence_present):
        status = "blocked_freshness_attestation_evidence_missing"
        blockers = ["freshness_attestation_evidence_missing"]
    elif not current:
        status = "blocked_freshness_attestation_not_current"
        blockers = ["freshness_attestation_not_current"]
    else:
        status = "freshness_attestation_prepared"
        blockers = []

    digest = aggregate_sha256(
        [
            {
                "source_path": source_path,
                "freshness_receipt_sha256": freshness_sha256,
                "freshness_attestor_invocation_sha256": (
                    None if invocation_model is None else invocation_model.sha256
                ),
                "provider_response_receipt_sha256": response_sha256,
                "status": status,
            }
        ]
    )
    return ProductionLiveFreshnessAttestationDecision(
        source_path=source_path,
        sha256=digest,
        status=status,
        gate_id=receipt_model.gate_id,
        freshness_receipt_sha256=freshness_sha256,
        provider_response_receipt_sha256=response_sha256,
        source_observation_path=receipt_model.source_observation_path,
        route_scope_ref=receipt_model.route_scope_ref,
        provider_request_ref=receipt_model.provider_request_ref,
        provider_evidence_ref=receipt_model.provider_evidence_ref,
        provider_evidence_sha256=receipt_model.provider_evidence_sha256,
        freshness_attestor_invocation_sha256=(
            None if invocation_model is None else invocation_model.sha256
        ),
        freshness_attestation_execution_ref=(
            receipt_model.freshness_attestation_execution_ref
        ),
        freshness_attestation_execution_sha256=(
            receipt_model.freshness_attestation_execution_sha256
        ),
        freshness_attestation_ref=receipt_model.freshness_attestation_ref,
        freshness_attestation_sha256=receipt_model.freshness_attestation_sha256,
        source_age_minutes=receipt_model.source_age_minutes,
        freshness_requirement_minutes=receipt_model.freshness_requirement_minutes,
        freshness_status=receipt_model.freshness_status,
        freshness_check_performed=freshness_check_performed,
        freshness_evidence_present=evidence_present,
        freshness_attestor_invocation_authorized=(
            invocation_model is not None and invocation_authorized
        ),
        freshness_attestor_invocation_lineage_match=(
            invocation_model is not None and invocation_lineage_match
        ),
        freshness_attestation_current=current,
        freshness_attestation_prepared=(
            status == "freshness_attestation_prepared"
        ),
        blockers=blockers,
        limitations=[
            "local freshness attestation receipt intake only",
            "does not perform freshness checks, call provider APIs, ingest runtime data, call safety APIs, mutate Phase 1, or expose credential/raw-location material",
        ],
    )


def execute_live_freshness_attestation_check_with_client(
    freshness_attestor_invocation: (
        ProductionLiveFreshnessAttestorInvocationReceipt | dict[str, Any]
    ),
    freshness_attestation_client: Callable[
        [ProductionLiveFreshnessAttestationExecutionRequest],
        ProductionLiveFreshnessAttestationExecutionResult | dict[str, Any],
    ],
    *,
    source_path: str = "inline:production-live-freshness-attestation-execution",
) -> ProductionLiveFreshnessAttestationExecutionDecision:
    invocation_model = (
        freshness_attestor_invocation
        if isinstance(
            freshness_attestor_invocation,
            ProductionLiveFreshnessAttestorInvocationReceipt,
        )
        else ProductionLiveFreshnessAttestorInvocationReceipt.model_validate(
            freshness_attestor_invocation
        )
    )
    invocation_authorized = (
        invocation_model.status == "freshness_attestor_invocation_authorized"
        and invocation_model.freshness_attestor_invocation_authorized
    )
    status: ProductionLiveFreshnessAttestationExecutionStatus
    blockers: list[str]
    execution_request_sha256: str | None = None
    freshness_receipt_sha256: str | None = None
    freshness_receipt: ProductionLiveFreshnessAttestationReceipt | None = None
    client_called = False
    client_result_valid = False
    client_effect_present = False

    if not invocation_authorized:
        status = "blocked_freshness_attestor_invocation_not_authorized"
        blockers = ["freshness_attestor_invocation_not_authorized"]
    else:
        execution_request = ProductionLiveFreshnessAttestationExecutionRequest(
            gate_id=invocation_model.gate_id,
            freshness_attestor_invocation_sha256=invocation_model.sha256,
            freshness_attestor_invocation_request_sha256=(
                invocation_model.freshness_attestor_invocation_request_sha256
            ),
            source_observation_path=invocation_model.source_observation_path,
            route_scope_ref=invocation_model.route_scope_ref,
            provider_request_ref=invocation_model.provider_request_ref,
            provider_response_receipt_sha256=(
                invocation_model.provider_response_receipt_sha256
            ),
            provider_evidence_ref=invocation_model.provider_evidence_ref or "",
            provider_evidence_sha256=invocation_model.provider_evidence_sha256
            or "",
            freshness_requirement_minutes=(
                invocation_model.freshness_requirement_minutes
            ),
            freshness_attestation_execution_ref=(
                invocation_model.freshness_attestation_execution_ref or ""
            ),
            freshness_attestation_execution_sha256=(
                invocation_model.freshness_attestation_execution_sha256 or ""
            ),
            reviewed_freshness_attestor_effect_boundary_ref=(
                invocation_model.reviewed_freshness_attestor_effect_boundary_ref
                or ""
            ),
            reviewed_freshness_attestor_effect_boundary_sha256=(
                invocation_model.reviewed_freshness_attestor_effect_boundary_sha256
                or ""
            ),
            fallback_plan_ref=invocation_model.fallback_plan_ref or "",
            fallback_plan_sha256=invocation_model.fallback_plan_sha256 or "",
            operator_identity_ref=invocation_model.operator_identity_ref,
            operator_identity_sha256=invocation_model.operator_identity_sha256,
            operator_role=invocation_model.operator_role,
            idempotency_key=invocation_model.idempotency_key,
        )
        execution_request_sha256 = (
            _live_freshness_attestation_execution_request_sha256(
                execution_request
            )
        )
        client_called = True
        try:
            client_result = freshness_attestation_client(execution_request)
            result_model = (
                client_result
                if isinstance(
                    client_result,
                    ProductionLiveFreshnessAttestationExecutionResult,
                )
                else ProductionLiveFreshnessAttestationExecutionResult.model_validate(
                    client_result
                )
            )
        except Exception:  # noqa: BLE001
            status = "blocked_freshness_client_result_invalid"
            blockers = ["freshness_client_result_invalid"]
        else:
            client_result_valid = True
            client_effect_present = bool(
                result_model.executor_reported_freshness_check_performed
                and result_model.freshness_attestation_ref
                and result_model.freshness_attestation_sha256
                and result_model.provider_evidence_ref
                and result_model.provider_evidence_sha256
            )
            lineage_match = (
                result_model.gate_id == invocation_model.gate_id
                and result_model.route_scope_ref == invocation_model.route_scope_ref
                and result_model.source_observation_path
                == invocation_model.source_observation_path
                and result_model.provider_request_ref
                == invocation_model.provider_request_ref
                and result_model.provider_response_receipt_sha256
                == invocation_model.provider_response_receipt_sha256
                and result_model.provider_evidence_ref
                == invocation_model.provider_evidence_ref
                and result_model.provider_evidence_sha256
                == invocation_model.provider_evidence_sha256
                and result_model.freshness_requirement_minutes
                == invocation_model.freshness_requirement_minutes
            )
            if not lineage_match:
                status = "blocked_freshness_client_result_invalid"
                blockers = ["freshness_client_result_invalid"]
            elif not client_effect_present:
                status = "blocked_freshness_client_effect_missing"
                blockers = ["freshness_client_effect_missing"]
            else:
                try:
                    freshness_receipt = ProductionLiveFreshnessAttestationReceipt(
                        source_provider=result_model.source_provider,
                        source_path=result_model.source_path,
                        gate_id=invocation_model.gate_id,
                        source_observation_path=(
                            invocation_model.source_observation_path
                        ),
                        route_scope_ref=invocation_model.route_scope_ref,
                        provider_request_ref=invocation_model.provider_request_ref,
                        provider_response_receipt_sha256=(
                            invocation_model.provider_response_receipt_sha256
                        ),
                        provider_evidence_ref=invocation_model.provider_evidence_ref,
                        provider_evidence_sha256=(
                            invocation_model.provider_evidence_sha256
                        ),
                        freshness_attestor_invocation_sha256=(
                            invocation_model.sha256
                        ),
                        freshness_attestation_execution_ref=(
                            invocation_model.freshness_attestation_execution_ref
                        ),
                        freshness_attestation_execution_sha256=(
                            invocation_model.freshness_attestation_execution_sha256
                        ),
                        freshness_attestation_ref=(
                            result_model.freshness_attestation_ref
                        ),
                        freshness_attestation_sha256=(
                            result_model.freshness_attestation_sha256
                        ),
                        source_age_minutes=result_model.source_age_minutes,
                        freshness_requirement_minutes=(
                            result_model.freshness_requirement_minutes
                        ),
                        freshness_status=result_model.freshness_status,
                        attested_current=result_model.attested_current,
                        route_context=result_model.route_context,
                        confidence=result_model.confidence,
                        executor_reported_freshness_check_performed=(
                            result_model.executor_reported_freshness_check_performed
                        ),
                    )
                except Exception:  # noqa: BLE001
                    freshness_receipt = None
                    status = "blocked_freshness_client_result_invalid"
                    blockers = ["freshness_client_result_invalid"]
                else:
                    status = "freshness_attestation_receipt_emitted"
                    blockers = []
                    freshness_receipt_sha256 = (
                        _live_freshness_attestation_receipt_sha256(
                            freshness_receipt
                        )
                    )

    digest = aggregate_sha256(
        [
            {
                "source_path": source_path,
                "freshness_attestor_invocation_sha256": invocation_model.sha256,
                "execution_request_sha256": execution_request_sha256,
                "freshness_receipt_sha256": freshness_receipt_sha256,
                "status": status,
            }
        ]
    )
    return ProductionLiveFreshnessAttestationExecutionDecision(
        source_path=source_path,
        sha256=digest,
        status=status,
        gate_id=invocation_model.gate_id,
        freshness_attestor_invocation_sha256=invocation_model.sha256,
        freshness_attestation_execution_ref=(
            invocation_model.freshness_attestation_execution_ref
        ),
        freshness_attestation_execution_sha256=(
            invocation_model.freshness_attestation_execution_sha256
        ),
        execution_request_sha256=execution_request_sha256,
        freshness_receipt_sha256=freshness_receipt_sha256,
        freshness_receipt=freshness_receipt,
        freshness_attestor_invocation_authorized=invocation_authorized,
        freshness_attestation_client_called=client_called,
        freshness_attestation_client_result_valid=client_result_valid,
        freshness_attestation_client_effect_present=client_effect_present,
        blockers=blockers,
        limitations=[
            "local injected freshness attestation client harness only",
            "does not call provider APIs, ingest runtime data, call safety APIs, mutate Phase 1, invoke transport, control hardware, or expose credential/raw-location material",
        ],
    )


def evaluate_live_provider_executor_effect_boundary_readiness(
    request_readiness: ProductionLiveProviderRequestReadinessReceipt | dict[str, Any],
    executor_manifest: (
        ProductionLiveProviderExecutorEffectBoundaryManifest | dict[str, Any]
    ),
    *,
    source_path: str = "inline:production-live-provider-executor-readiness",
) -> ProductionLiveProviderExecutorReadinessDecision:
    readiness_model = (
        request_readiness
        if isinstance(request_readiness, ProductionLiveProviderRequestReadinessReceipt)
        else ProductionLiveProviderRequestReadinessReceipt.model_validate(
            request_readiness
        )
    )
    manifest_model = (
        executor_manifest
        if isinstance(
            executor_manifest,
            ProductionLiveProviderExecutorEffectBoundaryManifest,
        )
        else ProductionLiveProviderExecutorEffectBoundaryManifest.model_validate(
            executor_manifest
        )
    )
    manifest_sha256 = _live_provider_executor_manifest_sha256(manifest_model)
    request_authorized = (
        readiness_model.status == "provider_request_boundary_authorized"
        and readiness_model.provider_request_boundary_authorized
    )
    lineage_match = _live_provider_executor_manifest_matches_readiness(
        readiness_model,
        manifest_model,
    )
    provider_executor_boundary_present = bool(
        manifest_model.provider_effect_boundary_ref
        and manifest_model.provider_effect_boundary_sha256
        and manifest_model.credential_ref
    )
    response_verifier_present = bool(
        manifest_model.response_verifier_ref
        and manifest_model.response_verifier_sha256
    )
    freshness_attestor_present = bool(
        manifest_model.freshness_attestor_ref
        and manifest_model.freshness_attestor_sha256
    )
    field_device_validator_present = bool(
        manifest_model.field_device_validator_ref
        and manifest_model.field_device_validator_sha256
    )
    fallback_plan_present = bool(
        manifest_model.fallback_plan_ref and manifest_model.fallback_plan_sha256
    )
    status: ProductionLiveProviderExecutorReadinessStatus
    blockers: list[str]

    if not request_authorized:
        status = "blocked_provider_request_not_authorized"
        blockers = ["provider_request_not_authorized"]
    elif not lineage_match:
        status = "blocked_provider_executor_lineage_mismatch"
        blockers = ["provider_executor_lineage_mismatch"]
    elif not provider_executor_boundary_present:
        status = "blocked_provider_executor_boundary_missing"
        blockers = ["provider_executor_boundary_missing"]
    elif not response_verifier_present:
        status = "blocked_response_verifier_missing"
        blockers = ["response_verifier_missing"]
    elif not freshness_attestor_present:
        status = "blocked_freshness_attestor_missing"
        blockers = ["freshness_attestor_missing"]
    elif not field_device_validator_present:
        status = "blocked_field_device_validator_missing"
        blockers = ["field_device_validator_missing"]
    elif not fallback_plan_present:
        status = "blocked_fallback_plan_missing"
        blockers = ["fallback_plan_missing"]
    else:
        status = "ready_for_reviewed_provider_effect_boundary"
        blockers = []

    digest = aggregate_sha256(
        [
            {
                "source_path": source_path,
                "request_readiness_sha256": readiness_model.sha256,
                "provider_executor_manifest_sha256": manifest_sha256,
                "status": status,
            }
        ]
    )
    return ProductionLiveProviderExecutorReadinessDecision(
        source_path=source_path,
        sha256=digest,
        status=status,
        gate_id=readiness_model.gate_id,
        connector_id=readiness_model.connector_id,
        provider_request_readiness_sha256=readiness_model.sha256,
        provider_executor_manifest_sha256=manifest_sha256,
        connector_manifest_sha256=readiness_model.manifest_sha256,
        request_contract_sha256=readiness_model.request_contract_sha256,
        source_observation_path=readiness_model.source_observation_path,
        route_scope_ref=readiness_model.route_scope_ref,
        provider_request_ref=readiness_model.provider_request_ref,
        provider_request_sha256=readiness_model.provider_request_sha256,
        credential_ref_present=bool(manifest_model.credential_ref),
        provider_effect_boundary_ref=manifest_model.provider_effect_boundary_ref,
        provider_effect_boundary_sha256=(
            manifest_model.provider_effect_boundary_sha256
        ),
        response_verifier_ref=manifest_model.response_verifier_ref,
        response_verifier_sha256=manifest_model.response_verifier_sha256,
        freshness_attestor_ref=manifest_model.freshness_attestor_ref,
        freshness_attestor_sha256=manifest_model.freshness_attestor_sha256,
        field_device_validator_ref=manifest_model.field_device_validator_ref,
        field_device_validator_sha256=(
            manifest_model.field_device_validator_sha256
        ),
        fallback_plan_ref=manifest_model.fallback_plan_ref,
        fallback_plan_sha256=manifest_model.fallback_plan_sha256,
        provider_request_authorized=request_authorized,
        lineage_match=lineage_match,
        provider_executor_boundary_present=provider_executor_boundary_present,
        response_verifier_present=response_verifier_present,
        freshness_attestor_present=freshness_attestor_present,
        field_device_validator_present=field_device_validator_present,
        fallback_plan_present=fallback_plan_present,
        ready_for_reviewed_provider_effect_boundary=(
            status == "ready_for_reviewed_provider_effect_boundary"
        ),
        blockers=blockers,
        limitations=[
            "local provider executor readiness only",
            "does not check connector health live, call provider APIs, ingest runtime data, call safety APIs, mutate Phase 1, or expose credential/raw-location material",
        ],
    )


def evaluate_live_provider_executor_invocation_guard(
    executor_readiness: ProductionLiveProviderExecutorReadinessDecision | dict[str, Any],
    invocation_request: (
        ProductionLiveProviderExecutorInvocationRequest | dict[str, Any]
    ),
    *,
    source_path: str = "inline:production-live-provider-executor-invocation",
) -> ProductionLiveProviderExecutorInvocationReceipt:
    readiness_model = (
        executor_readiness
        if isinstance(
            executor_readiness,
            ProductionLiveProviderExecutorReadinessDecision,
        )
        else ProductionLiveProviderExecutorReadinessDecision.model_validate(
            executor_readiness
        )
    )
    request_model = (
        invocation_request
        if isinstance(
            invocation_request,
            ProductionLiveProviderExecutorInvocationRequest,
        )
        else ProductionLiveProviderExecutorInvocationRequest.model_validate(
            invocation_request
        )
    )
    invocation_request_sha256 = _live_provider_executor_invocation_request_sha256(
        request_model
    )
    provider_executor_ready = (
        readiness_model.status == "ready_for_reviewed_provider_effect_boundary"
        and readiness_model.ready_for_reviewed_provider_effect_boundary
    )
    lineage_match = _live_provider_invocation_matches_readiness(
        readiness_model,
        request_model,
    )
    provider_effect_boundary_present = bool(
        request_model.provider_effect_boundary_ref
        and request_model.provider_effect_boundary_sha256
        and readiness_model.provider_executor_boundary_present
    )
    operator_identity_present = bool(
        request_model.operator_identity_ref and request_model.operator_identity_sha256
    )
    explicit_confirmation_present = (
        request_model.explicit_confirmation
        and request_model.confirmation_phrase
        == _LIVE_PROVIDER_EXECUTOR_INVOCATION_PHRASE
    )
    status: ProductionLiveProviderExecutorInvocationStatus
    blockers: list[str]
    provider_execution_ref: str | None = None
    provider_execution_sha256: str | None = None

    if not provider_executor_ready:
        status = "blocked_provider_executor_not_ready"
        blockers = ["provider_executor_not_ready"]
    elif not lineage_match:
        status = "blocked_provider_invocation_lineage_mismatch"
        blockers = ["provider_invocation_lineage_mismatch"]
    elif not provider_effect_boundary_present:
        status = "blocked_provider_effect_boundary_missing"
        blockers = ["provider_effect_boundary_missing"]
    elif not operator_identity_present:
        status = "blocked_provider_operator_identity_missing"
        blockers = ["provider_operator_identity_missing"]
    elif not explicit_confirmation_present:
        status = "blocked_explicit_provider_invocation_confirmation_missing"
        blockers = ["explicit_provider_invocation_confirmation_missing"]
    else:
        status = "provider_executor_invocation_authorized"
        blockers = []
        provider_execution_ref = (
            "provider://execution-boundary/"
            f"{request_model.connector_id}/{request_model.idempotency_key}"
        )
        provider_execution_sha256 = _live_provider_execution_sha256(
            readiness=readiness_model,
            request=request_model,
            invocation_request_sha256=invocation_request_sha256,
        )

    digest = aggregate_sha256(
        [
            {
                "source_path": source_path,
                "provider_executor_readiness_sha256": readiness_model.sha256,
                "invocation_request_sha256": invocation_request_sha256,
                "provider_execution_sha256": provider_execution_sha256,
                "status": status,
            }
        ]
    )
    return ProductionLiveProviderExecutorInvocationReceipt(
        source_path=source_path,
        sha256=digest,
        status=status,
        gate_id=readiness_model.gate_id,
        connector_id=readiness_model.connector_id,
        provider_executor_readiness_sha256=readiness_model.sha256,
        provider_request_readiness_sha256=(
            readiness_model.provider_request_readiness_sha256
        ),
        provider_executor_manifest_sha256=(
            readiness_model.provider_executor_manifest_sha256
        ),
        connector_manifest_sha256=readiness_model.connector_manifest_sha256,
        request_contract_sha256=readiness_model.request_contract_sha256,
        invocation_request_sha256=invocation_request_sha256,
        source_observation_path=readiness_model.source_observation_path,
        route_scope_ref=readiness_model.route_scope_ref,
        provider_request_ref=readiness_model.provider_request_ref or "",
        provider_request_sha256=readiness_model.provider_request_sha256 or "",
        provider_effect_boundary_ref=readiness_model.provider_effect_boundary_ref,
        provider_effect_boundary_sha256=(
            readiness_model.provider_effect_boundary_sha256
        ),
        response_verifier_ref=readiness_model.response_verifier_ref,
        response_verifier_sha256=readiness_model.response_verifier_sha256,
        freshness_attestor_ref=readiness_model.freshness_attestor_ref,
        freshness_attestor_sha256=readiness_model.freshness_attestor_sha256,
        field_device_validator_ref=readiness_model.field_device_validator_ref,
        field_device_validator_sha256=(
            readiness_model.field_device_validator_sha256
        ),
        fallback_plan_ref=readiness_model.fallback_plan_ref,
        fallback_plan_sha256=readiness_model.fallback_plan_sha256,
        operator_identity_ref=request_model.operator_identity_ref,
        operator_identity_sha256=request_model.operator_identity_sha256,
        operator_role=request_model.operator_role,
        idempotency_key=request_model.idempotency_key,
        provider_execution_ref=provider_execution_ref,
        provider_execution_sha256=provider_execution_sha256,
        provider_executor_ready=provider_executor_ready,
        lineage_match=lineage_match,
        provider_effect_boundary_present=provider_effect_boundary_present,
        operator_identity_present=operator_identity_present,
        explicit_confirmation_present=explicit_confirmation_present,
        provider_executor_invocation_authorized=(
            status == "provider_executor_invocation_authorized"
        ),
        blockers=blockers,
        limitations=[
            "local provider executor invocation guard only",
            "does not check connector health live, call provider APIs, ingest runtime data, call safety APIs, mutate Phase 1, or expose credential/raw-location material",
        ],
    )


def execute_live_provider_request_with_client(
    executor_readiness: ProductionLiveProviderExecutorReadinessDecision | dict[str, Any],
    provider_executor_invocation: (
        ProductionLiveProviderExecutorInvocationReceipt | dict[str, Any]
    ),
    provider_client: Callable[
        [ProductionLiveProviderExecutionRequest],
        ProductionLiveProviderExecutionResult | dict[str, Any],
    ],
    *,
    source_path: str = "inline:production-live-provider-execution",
) -> ProductionLiveProviderExecutionDecision:
    readiness_model = (
        executor_readiness
        if isinstance(
            executor_readiness,
            ProductionLiveProviderExecutorReadinessDecision,
        )
        else ProductionLiveProviderExecutorReadinessDecision.model_validate(
            executor_readiness
        )
    )
    invocation_model = (
        provider_executor_invocation
        if isinstance(
            provider_executor_invocation,
            ProductionLiveProviderExecutorInvocationReceipt,
        )
        else ProductionLiveProviderExecutorInvocationReceipt.model_validate(
            provider_executor_invocation
        )
    )
    provider_executor_ready = (
        readiness_model.status == "ready_for_reviewed_provider_effect_boundary"
        and readiness_model.ready_for_reviewed_provider_effect_boundary
    )
    invocation_authorized = (
        invocation_model.status == "provider_executor_invocation_authorized"
        and invocation_model.provider_executor_invocation_authorized
    )
    lineage_match = _live_provider_execution_invocation_matches_readiness(
        readiness_model,
        invocation_model,
    )
    status: ProductionLiveProviderExecutionStatus
    blockers: list[str]
    execution_request_sha256: str | None = None
    effect_receipt_sha256: str | None = None
    effect_receipt: ProductionLiveProviderEffectReceipt | None = None
    provider_client_called = False
    provider_client_result_valid = False
    provider_client_effect_present = False

    if not provider_executor_ready:
        status = "blocked_provider_executor_not_ready"
        blockers = ["provider_executor_not_ready"]
    elif not invocation_authorized:
        status = "blocked_provider_executor_invocation_not_authorized"
        blockers = ["provider_executor_invocation_not_authorized"]
    elif not lineage_match:
        status = "blocked_provider_execution_lineage_mismatch"
        blockers = ["provider_execution_lineage_mismatch"]
    else:
        execution_request = ProductionLiveProviderExecutionRequest(
            gate_id=invocation_model.gate_id,
            connector_id=invocation_model.connector_id,
            provider_executor_invocation_sha256=invocation_model.sha256,
            provider_executor_readiness_sha256=(
                invocation_model.provider_executor_readiness_sha256
            ),
            provider_request_readiness_sha256=(
                invocation_model.provider_request_readiness_sha256
            ),
            provider_executor_manifest_sha256=(
                invocation_model.provider_executor_manifest_sha256
            ),
            connector_manifest_sha256=invocation_model.connector_manifest_sha256,
            request_contract_sha256=invocation_model.request_contract_sha256,
            source_observation_path=invocation_model.source_observation_path,
            route_scope_ref=invocation_model.route_scope_ref,
            provider_request_ref=invocation_model.provider_request_ref,
            provider_request_sha256=invocation_model.provider_request_sha256,
            provider_execution_ref=invocation_model.provider_execution_ref or "",
            provider_execution_sha256=(
                invocation_model.provider_execution_sha256 or ""
            ),
            provider_effect_boundary_ref=(
                invocation_model.provider_effect_boundary_ref or ""
            ),
            provider_effect_boundary_sha256=(
                invocation_model.provider_effect_boundary_sha256 or ""
            ),
            response_verifier_ref=invocation_model.response_verifier_ref or "",
            response_verifier_sha256=(
                invocation_model.response_verifier_sha256 or ""
            ),
            freshness_attestor_ref=invocation_model.freshness_attestor_ref or "",
            freshness_attestor_sha256=(
                invocation_model.freshness_attestor_sha256 or ""
            ),
            field_device_validator_ref=(
                invocation_model.field_device_validator_ref or ""
            ),
            field_device_validator_sha256=(
                invocation_model.field_device_validator_sha256 or ""
            ),
            fallback_plan_ref=invocation_model.fallback_plan_ref or "",
            fallback_plan_sha256=invocation_model.fallback_plan_sha256 or "",
            operator_identity_ref=invocation_model.operator_identity_ref,
            operator_identity_sha256=invocation_model.operator_identity_sha256,
            operator_role=invocation_model.operator_role,
            credential_ref_present=readiness_model.credential_ref_present,
            idempotency_key=invocation_model.idempotency_key,
        )
        execution_request_sha256 = _live_provider_execution_request_sha256(
            execution_request
        )
        provider_client_called = True
        try:
            provider_result = provider_client(execution_request)
            result_model = (
                provider_result
                if isinstance(provider_result, ProductionLiveProviderExecutionResult)
                else ProductionLiveProviderExecutionResult.model_validate(
                    provider_result
                )
            )
        except Exception:  # noqa: BLE001
            status = "blocked_provider_client_result_invalid"
            blockers = ["provider_client_result_invalid"]
        else:
            provider_client_result_valid = True
            provider_client_effect_present = bool(
                result_model.executor_reported_provider_network_request_performed
                and result_model.executor_reported_real_provider_api_called
            )
            if result_model.source_observation_path != invocation_model.source_observation_path:
                status = "blocked_provider_client_result_invalid"
                blockers = ["provider_client_result_invalid"]
            elif not provider_client_effect_present:
                status = "blocked_provider_client_effect_missing"
                blockers = ["provider_client_effect_missing"]
            else:
                evidence_refs = list(
                    dict.fromkeys(
                        item
                        for item in (
                            *result_model.evidence_refs,
                            invocation_model.provider_request_ref,
                            invocation_model.provider_execution_ref,
                            result_model.provider_evidence_ref,
                            result_model.freshness_attestation_ref,
                            result_model.field_attestation_ref,
                            result_model.device_evidence_ref,
                        )
                        if item
                    )
                )
                try:
                    effect_receipt = ProductionLiveProviderEffectReceipt(
                        source_provider=result_model.source_provider,
                        source_path=result_model.source_path,
                        gate_id=invocation_model.gate_id,
                        connector_id=invocation_model.connector_id,
                        provider_executor_invocation_sha256=invocation_model.sha256,
                        provider_executor_readiness_sha256=(
                            invocation_model.provider_executor_readiness_sha256
                        ),
                        provider_request_readiness_sha256=(
                            invocation_model.provider_request_readiness_sha256
                        ),
                        provider_executor_manifest_sha256=(
                            invocation_model.provider_executor_manifest_sha256
                        ),
                        connector_manifest_sha256=(
                            invocation_model.connector_manifest_sha256
                        ),
                        request_contract_sha256=(
                            invocation_model.request_contract_sha256
                        ),
                        source_observation_path=(
                            invocation_model.source_observation_path
                        ),
                        route_scope_ref=invocation_model.route_scope_ref,
                        provider_request_ref=invocation_model.provider_request_ref,
                        provider_request_sha256=(
                            invocation_model.provider_request_sha256
                        ),
                        provider_execution_ref=(
                            invocation_model.provider_execution_ref or ""
                        ),
                        provider_execution_sha256=(
                            invocation_model.provider_execution_sha256 or ""
                        ),
                        provider_dataset_ids=result_model.provider_dataset_ids,
                        provider_evidence_ref=result_model.provider_evidence_ref,
                        provider_evidence_sha256=(
                            result_model.provider_evidence_sha256
                        ),
                        current_observation_ref=(
                            result_model.current_observation_ref
                        ),
                        freshness_attestation_ref=(
                            result_model.freshness_attestation_ref
                        ),
                        freshness_attestation_sha256=(
                            result_model.freshness_attestation_sha256
                        ),
                        source_age_minutes=result_model.source_age_minutes,
                        freshness_requirement_minutes=(
                            result_model.freshness_requirement_minutes
                        ),
                        response_status=result_model.response_status,
                        observed_at_offset_s=result_model.observed_at_offset_s,
                        warning_level=result_model.warning_level,
                        warning_type=result_model.warning_type,
                        wind_risk=result_model.wind_risk,
                        rain_risk=result_model.rain_risk,
                        lightning_risk=result_model.lightning_risk,
                        threat_type=result_model.threat_type,
                        passability=result_model.passability,
                        immediacy=result_model.immediacy,
                        route_blocked=result_model.route_blocked,
                        safe_bypass_known=result_model.safe_bypass_known,
                        field_attestation_ref=result_model.field_attestation_ref,
                        device_evidence_ref=result_model.device_evidence_ref,
                        route_pressure_review_required=(
                            result_model.route_pressure_review_required
                        ),
                        route_context=result_model.route_context,
                        evidence_refs=evidence_refs,
                        confidence=result_model.confidence,
                        executor_reported_provider_network_request_performed=(
                            result_model.executor_reported_provider_network_request_performed
                        ),
                        executor_reported_real_provider_api_called=(
                            result_model.executor_reported_real_provider_api_called
                        ),
                    )
                except Exception:  # noqa: BLE001
                    effect_receipt = None
                    status = "blocked_provider_client_result_invalid"
                    blockers = ["provider_client_result_invalid"]
                else:
                    status = "provider_effect_receipt_emitted"
                    blockers = []
                    effect_receipt_sha256 = _live_provider_effect_receipt_sha256(
                        effect_receipt
                    )

    digest = aggregate_sha256(
        [
            {
                "source_path": source_path,
                "provider_executor_readiness_sha256": readiness_model.sha256,
                "provider_executor_invocation_sha256": invocation_model.sha256,
                "execution_request_sha256": execution_request_sha256,
                "provider_effect_receipt_sha256": effect_receipt_sha256,
                "status": status,
            }
        ]
    )
    return ProductionLiveProviderExecutionDecision(
        source_path=source_path,
        sha256=digest,
        status=status,
        gate_id=invocation_model.gate_id,
        connector_id=invocation_model.connector_id,
        provider_executor_invocation_sha256=invocation_model.sha256,
        provider_executor_readiness_sha256=readiness_model.sha256,
        provider_request_readiness_sha256=(
            invocation_model.provider_request_readiness_sha256
        ),
        provider_executor_manifest_sha256=(
            invocation_model.provider_executor_manifest_sha256
        ),
        connector_manifest_sha256=invocation_model.connector_manifest_sha256,
        request_contract_sha256=invocation_model.request_contract_sha256,
        source_observation_path=invocation_model.source_observation_path,
        route_scope_ref=invocation_model.route_scope_ref,
        provider_request_ref=invocation_model.provider_request_ref,
        provider_request_sha256=invocation_model.provider_request_sha256,
        provider_execution_ref=invocation_model.provider_execution_ref,
        provider_execution_sha256=invocation_model.provider_execution_sha256,
        execution_request_sha256=execution_request_sha256,
        provider_effect_receipt_sha256=effect_receipt_sha256,
        provider_effect_receipt=effect_receipt,
        provider_executor_ready=provider_executor_ready,
        provider_executor_invocation_authorized=invocation_authorized,
        provider_execution_lineage_match=lineage_match,
        provider_client_called=provider_client_called,
        provider_client_result_valid=provider_client_result_valid,
        provider_client_effect_present=provider_client_effect_present,
        blockers=blockers,
        limitations=[
            "live provider executor harness requires an injected reviewed provider client",
            "tests use fake provider clients; no credential value, raw provider payload, runtime ingest, safety API call, Phase 1 mutation, outbound transport, or hardware control is performed by this local verifier",
        ],
    )


def build_provider_response_receipt_from_provider_effect_receipt(
    provider_executor_invocation: (
        ProductionLiveProviderExecutorInvocationReceipt | dict[str, Any]
    ),
    provider_effect_receipt: ProductionLiveProviderEffectReceipt | dict[str, Any],
    *,
    source_path: str = "inline:production-live-provider-effect-receipt-intake",
) -> ProductionLiveProviderEffectReceiptIntakeDecision:
    invocation_model = (
        provider_executor_invocation
        if isinstance(
            provider_executor_invocation,
            ProductionLiveProviderExecutorInvocationReceipt,
        )
        else ProductionLiveProviderExecutorInvocationReceipt.model_validate(
            provider_executor_invocation
        )
    )
    effect_model = (
        provider_effect_receipt
        if isinstance(provider_effect_receipt, ProductionLiveProviderEffectReceipt)
        else ProductionLiveProviderEffectReceipt.model_validate(provider_effect_receipt)
    )
    effect_receipt_sha256 = _live_provider_effect_receipt_sha256(effect_model)
    invocation_authorized = (
        invocation_model.status == "provider_executor_invocation_authorized"
        and invocation_model.provider_executor_invocation_authorized
    )
    lineage_match = _live_provider_effect_matches_invocation(
        invocation_model,
        effect_model,
    )
    evidence_present = _live_provider_effect_evidence_present(effect_model)
    effect_successful = (
        effect_model.response_status == "success"
        and effect_model.executor_reported_provider_network_request_performed
        and effect_model.executor_reported_real_provider_api_called
    )
    response_receipt: ProductionLiveProviderResponseReceipt | None = None
    response_receipt_sha256: str | None = None
    status: ProductionLiveProviderEffectReceiptIntakeStatus
    blockers: list[str]

    if not invocation_authorized:
        status = "blocked_provider_executor_invocation_not_authorized"
        blockers = ["provider_executor_invocation_not_authorized"]
    elif not lineage_match:
        status = "blocked_provider_effect_lineage_mismatch"
        blockers = ["provider_effect_lineage_mismatch"]
    elif not evidence_present:
        status = "blocked_provider_effect_evidence_missing"
        blockers = ["provider_effect_evidence_missing"]
    elif not effect_successful:
        status = "blocked_provider_effect_not_successful"
        blockers = ["provider_effect_not_successful"]
    else:
        status = "provider_response_receipt_prepared"
        blockers = []
        response_receipt = ProductionLiveProviderResponseReceipt(
            source_provider=effect_model.source_provider,
            source_path=effect_model.source_path,
            gate_id=effect_model.gate_id,
            connector_id=effect_model.connector_id,
            provider_request_readiness_sha256=(
                effect_model.provider_request_readiness_sha256
            ),
            manifest_sha256=effect_model.connector_manifest_sha256,
            request_contract_sha256=effect_model.request_contract_sha256,
            source_observation_path=effect_model.source_observation_path,
            route_scope_ref=effect_model.route_scope_ref,
            provider_request_ref=effect_model.provider_request_ref,
            provider_request_sha256=effect_model.provider_request_sha256,
            provider_executor_invocation_sha256=invocation_model.sha256,
            provider_execution_ref=effect_model.provider_execution_ref,
            provider_execution_sha256=effect_model.provider_execution_sha256,
            provider_dataset_ids=effect_model.provider_dataset_ids,
            provider_evidence_ref=effect_model.provider_evidence_ref,
            provider_evidence_sha256=effect_model.provider_evidence_sha256,
            current_observation_ref=effect_model.current_observation_ref,
            freshness_attestation_ref=effect_model.freshness_attestation_ref,
            freshness_attestation_sha256=effect_model.freshness_attestation_sha256,
            source_age_minutes=effect_model.source_age_minutes,
            freshness_requirement_minutes=effect_model.freshness_requirement_minutes,
            response_status=effect_model.response_status,
            observed_at_offset_s=effect_model.observed_at_offset_s,
            warning_level=effect_model.warning_level,
            warning_type=effect_model.warning_type,
            wind_risk=effect_model.wind_risk,
            rain_risk=effect_model.rain_risk,
            lightning_risk=effect_model.lightning_risk,
            threat_type=effect_model.threat_type,
            passability=effect_model.passability,
            immediacy=effect_model.immediacy,
            route_blocked=effect_model.route_blocked,
            safe_bypass_known=effect_model.safe_bypass_known,
            field_attestation_ref=effect_model.field_attestation_ref,
            device_evidence_ref=effect_model.device_evidence_ref,
            route_pressure_review_required=(
                effect_model.route_pressure_review_required
            ),
            route_context=effect_model.route_context,
            evidence_refs=effect_model.evidence_refs,
            confidence=effect_model.confidence,
            executor_reported_provider_network_request_performed=(
                effect_model.executor_reported_provider_network_request_performed
            ),
            executor_reported_real_provider_api_called=(
                effect_model.executor_reported_real_provider_api_called
            ),
        )
        response_receipt_sha256 = _live_provider_response_receipt_sha256(
            response_receipt
        )

    digest = aggregate_sha256(
        [
            {
                "source_path": source_path,
                "provider_executor_invocation_sha256": invocation_model.sha256,
                "provider_effect_receipt_sha256": effect_receipt_sha256,
                "response_receipt_sha256": response_receipt_sha256,
                "status": status,
            }
        ]
    )
    return ProductionLiveProviderEffectReceiptIntakeDecision(
        source_path=source_path,
        sha256=digest,
        status=status,
        gate_id=effect_model.gate_id,
        connector_id=effect_model.connector_id,
        provider_effect_receipt_sha256=effect_receipt_sha256,
        provider_executor_invocation_sha256=invocation_model.sha256,
        provider_executor_readiness_sha256=(
            effect_model.provider_executor_readiness_sha256
        ),
        provider_request_readiness_sha256=(
            effect_model.provider_request_readiness_sha256
        ),
        provider_executor_manifest_sha256=(
            effect_model.provider_executor_manifest_sha256
        ),
        connector_manifest_sha256=effect_model.connector_manifest_sha256,
        request_contract_sha256=effect_model.request_contract_sha256,
        source_observation_path=effect_model.source_observation_path,
        route_scope_ref=effect_model.route_scope_ref,
        provider_request_ref=effect_model.provider_request_ref,
        provider_request_sha256=effect_model.provider_request_sha256,
        provider_execution_ref=effect_model.provider_execution_ref,
        provider_execution_sha256=effect_model.provider_execution_sha256,
        provider_evidence_ref=effect_model.provider_evidence_ref,
        provider_evidence_sha256=effect_model.provider_evidence_sha256,
        response_receipt_sha256=response_receipt_sha256,
        response_receipt=response_receipt,
        provider_executor_invocation_authorized=invocation_authorized,
        provider_effect_lineage_match=lineage_match,
        provider_effect_evidence_present=evidence_present,
        provider_effect_successful=effect_successful,
        response_receipt_prepared=status == "provider_response_receipt_prepared",
        blockers=blockers,
        limitations=[
            "local provider effect receipt intake only",
            "does not check connector health live, call provider APIs, ingest runtime data, call safety APIs, mutate Phase 1, or expose credential/raw-location material",
        ],
    )


def build_runtime_safety_gate_events_from_fixture(
    payload: dict[str, Any],
):
    events = []
    if "pace" in payload:
        events.append(build_pace_gate_event(payload["pace"]))
    if "delay" in payload:
        events.append(build_delay_gate_event(payload["delay"]))
    if "darkness" in payload:
        events.append(build_darkness_gate_event(payload["darkness"]))
    if "weather" in payload:
        events.append(build_weather_gate_event(payload["weather"]))
    if "environment_threat" in payload:
        events.append(build_environment_threat_gate_event(payload["environment_threat"]))
    return events


def _weather_state_for_level(level: WeatherGateLevel):
    severity_by_level = {
        "none": ("none", "none", "weather_ok", "continue_monitoring"),
        "watch": ("watch", "candidate_watch", "weather_watch", "watch_weather"),
        "advisory": (
            "rest",
            "candidate_rest",
            "weather_rest_review",
            "pause_plan_and_recheck_weather",
        ),
        "unsafe": (
            "retreat_review",
            "candidate_retreat",
            "weather_retreat_review",
            "review_retreat_or_hold",
        ),
        "severe": (
            "alert_review",
            "candidate_alert_review",
            "weather_alert_review",
            "review_alert_hold_or_retreat",
        ),
    }
    return severity_by_level[level]


def _threat_state_for_observation(
    *,
    passability: EnvironmentThreatPassability,
    immediacy: EnvironmentThreatImmediacy,
    route_blocked: bool,
    safe_bypass_known: bool,
):
    severity = "watch"
    transition = "candidate_watch"
    state = "environment_threat_watch"
    action = "watch_environment_threat"
    reasons: list[str] = []

    if route_blocked or passability == "blocked":
        severity = "retreat_review"
        transition = "candidate_retreat"
        state = "environment_route_blocked_review"
        action = "review_retreat_or_safe_bypass"
        reasons.append("route is blocked or no longer passable")
    elif immediacy == "immediate" and not safe_bypass_known:
        severity = "alert_review"
        transition = "candidate_alert_review"
        state = "environment_immediate_threat_review"
        action = "review_hold_retreat_or_alert"
        reasons.append("immediate threat without known safe bypass")
    elif passability == "limited" or immediacy == "nearby":
        severity = "rest"
        transition = "candidate_rest"
        state = "environment_rest_review"
        action = "stop_and_review_route"
        reasons.append("field hazard limits route confidence")

    return severity, transition, state, action, reasons


def _assert_production_live_source(source_provider: str, source_path: str) -> None:
    lower_provider = source_provider.casefold()
    if source_path.startswith("inline:") or "fixture" in lower_provider or "test" in lower_provider:
        raise ValueError("production live observation cannot use fixture or inline source")
    _assert_ref_prefix(
        "source_path",
        source_path,
        _PRODUCTION_LIVE_SOURCE_PREFIXES,
    )
    _assert_no_safety_api_ref("source_path", source_path)


def _assert_ref_prefix(
    field_name: str,
    value: str,
    prefixes: tuple[str, ...],
) -> None:
    if not value.startswith(prefixes):
        raise ValueError(f"{field_name} must use a production live reference")
    _assert_no_safety_api_ref(field_name, value)


def _assert_no_safety_api_ref(field_name: str, value: str) -> None:
    if "/safety/" in value:
        raise ValueError(f"{field_name} cannot reference a safety API path")


def _assert_secret_ref(value: str) -> None:
    if not value.startswith(_PRODUCTION_SECRET_REF_PREFIXES):
        raise ValueError("credential_ref must use an approved secret reference")
    if "=" in value or " " in value:
        raise ValueError("credential_ref cannot embed credential material")
    lowered = value.casefold()
    if lowered.startswith(("sk-", "bearer", "basic")):
        raise ValueError("credential_ref cannot embed credential material")


def _assert_route_scope(route_context: SafetyGateRouteContext) -> None:
    if not route_context.route_id:
        raise ValueError("production live observation requires route_id")
    if not (
        route_context.segment_id
        or route_context.checkpoint_id
        or route_context.map_target_ids
    ):
        raise ValueError("production live observation requires route segment or target")


def _assert_no_adapter_effects(
    *,
    adapter_network_request_performed: bool,
    real_provider_api_called_by_adapter: bool,
    runtime_ingest_performed_by_adapter: bool,
    safety_api_called: bool,
    phase1_l0_l4_state_mutated: bool,
) -> None:
    if (
        adapter_network_request_performed
        or real_provider_api_called_by_adapter
        or runtime_ingest_performed_by_adapter
        or safety_api_called
        or phase1_l0_l4_state_mutated
    ):
        raise ValueError("production live observation bridge cannot perform effects")


def _live_observation_sha256(payload: dict[str, Any], *, artifact: str) -> str:
    return aggregate_sha256(
        [
            {
                "artifact": artifact,
                "payload": payload,
                "adapter_network_request_performed": False,
                "runtime_ingest_performed_by_adapter": False,
            }
        ]
    )


def _live_provider_manifest_sha256(
    manifest: ProductionLiveProviderConnectorManifest,
) -> str:
    return aggregate_sha256(
        [
            {
                "artifact": manifest.artifact_kind,
                "payload": manifest.model_dump(mode="json"),
                "network_request_performed": False,
                "runtime_ingest_performed": False,
            }
        ]
    )


def _live_provider_request_contract_sha256(
    *,
    manifest_sha256: str,
    request: ProductionLiveProviderRequestContract,
) -> str:
    return aggregate_sha256(
        [
            {
                "artifact": request.artifact_kind,
                "manifest_sha256": manifest_sha256,
                "payload": request.model_dump(mode="json"),
                "network_request_performed": False,
                "runtime_ingest_performed": False,
            }
        ]
    )


def _live_provider_request_sha256(
    *,
    manifest_sha256: str,
    request_contract_sha256: str,
    request: ProductionLiveProviderRequestContract,
) -> str:
    return aggregate_sha256(
        [
            {
                "artifact": "scout_production_live_provider_request_boundary_ref",
                "manifest_sha256": manifest_sha256,
                "request_contract_sha256": request_contract_sha256,
                "gate_id": request.gate_id,
                "connector_id": request.connector_id,
                "idempotency_key": request.idempotency_key,
                "execution_mode": request.execution_mode,
                "effect_boundary_ref": request.reviewed_provider_effect_boundary_ref,
                "network_request_performed": False,
            }
        ]
    )


def _live_provider_response_receipt_sha256(
    receipt: ProductionLiveProviderResponseReceipt,
) -> str:
    return aggregate_sha256(
        [
            {
                "artifact": receipt.artifact_kind,
                "payload": receipt.model_dump(mode="json"),
                "runtime_ingest_performed": False,
                "safety_api_called": False,
            }
        ]
    )


def _live_connector_health_receipt_sha256(
    receipt: ProductionLiveConnectorHealthReceipt,
) -> str:
    return aggregate_sha256(
        [
            {
                "artifact": receipt.artifact_kind,
                "payload": receipt.model_dump(mode="json"),
                "runtime_ingest_performed": False,
                "safety_api_called": False,
            }
        ]
    )


def _live_connector_health_invocation_request_sha256(
    request: ProductionLiveConnectorHealthExecutorInvocationRequest,
) -> str:
    return aggregate_sha256(
        [
            {
                "artifact": request.artifact_kind,
                "payload": request.model_dump(mode="json"),
                "connector_health_checked": False,
                "provider_network_request_performed": False,
                "runtime_ingest_performed": False,
                "safety_api_called": False,
            }
        ]
    )


def _live_connector_health_execution_sha256(
    *,
    request: ProductionLiveConnectorHealthExecutorInvocationRequest,
    invocation_request_sha256: str,
) -> str:
    return aggregate_sha256(
        [
            {
                "artifact": "scout_production_live_connector_health_execution_boundary_ref",
                "connector_health_invocation_request_sha256": (
                    invocation_request_sha256
                ),
                "gate_id": request.gate_id,
                "connector_id": request.connector_id,
                "source_path": request.source_path,
                "route_scope_ref": request.route_scope_ref,
                "effect_boundary_ref": (
                    request.reviewed_connector_health_effect_boundary_ref
                ),
                "operator_identity_ref": request.operator_identity_ref,
                "idempotency_key": request.idempotency_key,
                "connector_health_checked": False,
                "runtime_ingest_performed": False,
                "safety_api_called": False,
            }
        ]
    )


def _live_connector_health_execution_request_sha256(
    request: ProductionLiveConnectorHealthExecutionRequest,
) -> str:
    return aggregate_sha256(
        [
            {
                "artifact": request.artifact_kind,
                "payload": request.model_dump(mode="json"),
                "runtime_ingest_performed": False,
                "safety_api_called": False,
                "phase1_l0_l4_state_mutated": False,
            }
        ]
    )


def _live_connector_health_receipt_matches_invocation(
    invocation: ProductionLiveConnectorHealthExecutorInvocationReceipt,
    receipt: ProductionLiveConnectorHealthReceipt,
) -> bool:
    return (
        receipt.connector_health_invocation_sha256 == invocation.sha256
        and receipt.connector_health_execution_ref
        == invocation.connector_health_execution_ref
        and receipt.connector_health_execution_sha256
        == invocation.connector_health_execution_sha256
        and receipt.gate_id == invocation.gate_id
        and receipt.connector_id == invocation.connector_id
        and receipt.provider_name == invocation.provider_name
        and receipt.provider_dataset_ids == invocation.provider_dataset_ids
        and receipt.source_path == invocation.source_observation_path
        and receipt.route_scope_ref == invocation.route_scope_ref
        and receipt.credential_ref == invocation.credential_ref
    )


def _live_field_device_validator_invocation_request_sha256(
    request: ProductionLiveFieldDeviceValidatorInvocationRequest,
) -> str:
    return aggregate_sha256(
        [
            {
                "artifact": request.artifact_kind,
                "payload": request.model_dump(mode="json"),
                "field_device_validation_performed": False,
                "provider_network_request_performed": False,
                "runtime_ingest_performed": False,
                "safety_api_called": False,
            }
        ]
    )


def _live_field_device_validator_execution_sha256(
    *,
    request: ProductionLiveFieldDeviceValidatorInvocationRequest,
    invocation_request_sha256: str,
) -> str:
    return aggregate_sha256(
        [
            {
                "artifact": (
                    "scout_production_live_field_device_validation_execution_boundary_ref"
                ),
                "field_device_validator_invocation_request_sha256": (
                    invocation_request_sha256
                ),
                "gate_id": request.gate_id,
                "source_observation_path": request.source_observation_path,
                "route_scope_ref": request.route_scope_ref,
                "provider_request_ref": request.provider_request_ref,
                "provider_response_receipt_sha256": (
                    request.provider_response_receipt_sha256
                ),
                "current_observation_ref": request.current_observation_ref,
                "device_evidence_ref": request.device_evidence_ref,
                "device_evidence_sha256": request.device_evidence_sha256,
                "effect_boundary_ref": (
                    request.reviewed_field_device_validator_effect_boundary_ref
                ),
                "operator_identity_ref": request.operator_identity_ref,
                "idempotency_key": request.idempotency_key,
                "field_device_validation_performed": False,
                "runtime_ingest_performed": False,
                "safety_api_called": False,
            }
        ]
    )


def _live_field_device_validation_matches_invocation(
    invocation: ProductionLiveFieldDeviceValidatorInvocationReceipt,
    receipt: ProductionLiveFieldDeviceValidationReceipt,
) -> bool:
    return (
        receipt.field_device_validator_invocation_sha256 == invocation.sha256
        and receipt.field_device_validation_execution_ref
        == invocation.field_device_validation_execution_ref
        and receipt.field_device_validation_execution_sha256
        == invocation.field_device_validation_execution_sha256
        and receipt.gate_id == invocation.gate_id
        and (
            invocation.source_observation_path is None
            or receipt.source_observation_path == invocation.source_observation_path
        )
        and receipt.route_scope_ref == invocation.route_scope_ref
        and (
            invocation.provider_request_ref is None
            or receipt.provider_request_ref == invocation.provider_request_ref
        )
        and (
            invocation.provider_response_receipt_sha256 is None
            or receipt.provider_response_receipt_sha256
            == invocation.provider_response_receipt_sha256
        )
        and (
            invocation.current_observation_ref is None
            or receipt.current_observation_ref == invocation.current_observation_ref
        )
        and (
            invocation.device_evidence_ref is None
            or receipt.device_evidence_ref == invocation.device_evidence_ref
        )
        and (
            invocation.device_evidence_sha256 is None
            or receipt.device_evidence_sha256 == invocation.device_evidence_sha256
        )
    )


def _live_field_device_validation_receipt_sha256(
    receipt: ProductionLiveFieldDeviceValidationReceipt,
) -> str:
    return aggregate_sha256(
        [
            {
                "artifact": receipt.artifact_kind,
                "payload": receipt.model_dump(mode="json"),
                "runtime_ingest_performed": False,
                "safety_api_called": False,
            }
        ]
    )


def _live_field_device_validation_execution_request_sha256(
    request: ProductionLiveFieldDeviceValidationExecutionRequest,
) -> str:
    return aggregate_sha256(
        [
            {
                "artifact": request.artifact_kind,
                "payload": request.model_dump(mode="json"),
                "field_device_validation_performed": False,
                "provider_network_request_performed": False,
                "runtime_ingest_performed": False,
                "safety_api_called": False,
            }
        ]
    )


def _live_freshness_attestation_receipt_sha256(
    receipt: ProductionLiveFreshnessAttestationReceipt,
) -> str:
    return aggregate_sha256(
        [
            {
                "artifact": receipt.artifact_kind,
                "payload": receipt.model_dump(mode="json"),
                "runtime_ingest_performed": False,
                "safety_api_called": False,
            }
        ]
    )


def _live_freshness_attestation_execution_request_sha256(
    request: ProductionLiveFreshnessAttestationExecutionRequest,
) -> str:
    return aggregate_sha256(
        [
            {
                "artifact": request.artifact_kind,
                "payload": request.model_dump(mode="json"),
                "freshness_check_performed": False,
                "provider_network_request_performed": False,
                "runtime_ingest_performed": False,
                "safety_api_called": False,
            }
        ]
    )


def _live_freshness_attestor_invocation_request_sha256(
    request: ProductionLiveFreshnessAttestorInvocationRequest,
) -> str:
    return aggregate_sha256(
        [
            {
                "artifact": request.artifact_kind,
                "payload": request.model_dump(mode="json"),
                "freshness_check_performed": False,
                "provider_network_request_performed": False,
                "runtime_ingest_performed": False,
                "safety_api_called": False,
            }
        ]
    )


def _live_freshness_attestor_execution_sha256(
    *,
    request: ProductionLiveFreshnessAttestorInvocationRequest,
    invocation_request_sha256: str,
) -> str:
    return aggregate_sha256(
        [
            {
                "artifact": "scout_production_live_freshness_attestation_execution_boundary_ref",
                "freshness_attestor_invocation_request_sha256": (
                    invocation_request_sha256
                ),
                "gate_id": request.gate_id,
                "source_observation_path": request.source_observation_path,
                "route_scope_ref": request.route_scope_ref,
                "provider_request_ref": request.provider_request_ref,
                "provider_response_receipt_sha256": (
                    request.provider_response_receipt_sha256
                ),
                "provider_evidence_ref": request.provider_evidence_ref,
                "provider_evidence_sha256": request.provider_evidence_sha256,
                "freshness_requirement_minutes": (
                    request.freshness_requirement_minutes
                ),
                "effect_boundary_ref": (
                    request.reviewed_freshness_attestor_effect_boundary_ref
                ),
                "operator_identity_ref": request.operator_identity_ref,
                "idempotency_key": request.idempotency_key,
                "freshness_check_performed": False,
                "runtime_ingest_performed": False,
                "safety_api_called": False,
            }
        ]
    )


def _live_freshness_attestation_matches_invocation(
    invocation: ProductionLiveFreshnessAttestorInvocationReceipt,
    receipt: ProductionLiveFreshnessAttestationReceipt,
) -> bool:
    return (
        receipt.freshness_attestor_invocation_sha256 == invocation.sha256
        and receipt.freshness_attestation_execution_ref
        == invocation.freshness_attestation_execution_ref
        and receipt.freshness_attestation_execution_sha256
        == invocation.freshness_attestation_execution_sha256
        and receipt.gate_id == invocation.gate_id
        and (
            invocation.source_observation_path is None
            or receipt.source_observation_path == invocation.source_observation_path
        )
        and receipt.route_scope_ref == invocation.route_scope_ref
        and (
            invocation.provider_request_ref is None
            or receipt.provider_request_ref == invocation.provider_request_ref
        )
        and (
            invocation.provider_response_receipt_sha256 is None
            or receipt.provider_response_receipt_sha256
            == invocation.provider_response_receipt_sha256
        )
        and receipt.provider_evidence_ref == invocation.provider_evidence_ref
        and receipt.provider_evidence_sha256 == invocation.provider_evidence_sha256
        and receipt.freshness_requirement_minutes
        == invocation.freshness_requirement_minutes
    )


def _live_provider_executor_manifest_sha256(
    manifest: ProductionLiveProviderExecutorEffectBoundaryManifest,
) -> str:
    return aggregate_sha256(
        [
            {
                "artifact": manifest.artifact_kind,
                "payload": manifest.model_dump(mode="json"),
                "provider_network_request_performed": False,
                "runtime_ingest_performed": False,
                "safety_api_called": False,
            }
        ]
    )


def _live_provider_executor_manifest_matches_readiness(
    readiness: ProductionLiveProviderRequestReadinessReceipt,
    manifest: ProductionLiveProviderExecutorEffectBoundaryManifest,
) -> bool:
    return (
        manifest.provider_request_readiness_sha256 == readiness.sha256
        and manifest.connector_manifest_sha256 == readiness.manifest_sha256
        and manifest.request_contract_sha256 == readiness.request_contract_sha256
        and manifest.gate_id == readiness.gate_id
        and manifest.connector_id == readiness.connector_id
        and manifest.source_observation_path == readiness.source_observation_path
        and manifest.route_scope_ref == readiness.route_scope_ref
        and manifest.connector_health_ref == readiness.connector_health_ref
        and manifest.connector_health_sha256 == readiness.connector_health_sha256
        and manifest.provider_request_ref == readiness.provider_request_ref
        and manifest.provider_request_sha256 == readiness.provider_request_sha256
    )


def _live_provider_executor_invocation_request_sha256(
    request: ProductionLiveProviderExecutorInvocationRequest,
) -> str:
    return aggregate_sha256(
        [
            {
                "artifact": request.artifact_kind,
                "payload": request.model_dump(mode="json"),
                "provider_network_request_performed": False,
                "runtime_ingest_performed": False,
                "safety_api_called": False,
            }
        ]
    )


def _live_provider_execution_sha256(
    *,
    readiness: ProductionLiveProviderExecutorReadinessDecision,
    request: ProductionLiveProviderExecutorInvocationRequest,
    invocation_request_sha256: str,
) -> str:
    return aggregate_sha256(
        [
            {
                "artifact": "scout_production_live_provider_execution_boundary_ref",
                "provider_executor_readiness_sha256": readiness.sha256,
                "invocation_request_sha256": invocation_request_sha256,
                "gate_id": readiness.gate_id,
                "connector_id": readiness.connector_id,
                "provider_request_ref": readiness.provider_request_ref,
                "provider_request_sha256": readiness.provider_request_sha256,
                "provider_effect_boundary_ref": readiness.provider_effect_boundary_ref,
                "operator_identity_ref": request.operator_identity_ref,
                "idempotency_key": request.idempotency_key,
                "provider_network_request_performed": False,
                "runtime_ingest_performed": False,
                "safety_api_called": False,
            }
        ]
    )


def _live_provider_invocation_matches_readiness(
    readiness: ProductionLiveProviderExecutorReadinessDecision,
    request: ProductionLiveProviderExecutorInvocationRequest,
) -> bool:
    return (
        request.provider_executor_readiness_sha256 == readiness.sha256
        and request.provider_request_readiness_sha256
        == readiness.provider_request_readiness_sha256
        and request.provider_executor_manifest_sha256
        == readiness.provider_executor_manifest_sha256
        and request.connector_manifest_sha256 == readiness.connector_manifest_sha256
        and request.request_contract_sha256 == readiness.request_contract_sha256
        and request.gate_id == readiness.gate_id
        and request.connector_id == readiness.connector_id
        and request.source_observation_path == readiness.source_observation_path
        and request.route_scope_ref == readiness.route_scope_ref
        and request.provider_request_ref == readiness.provider_request_ref
        and request.provider_request_sha256 == readiness.provider_request_sha256
        and request.provider_effect_boundary_ref
        == readiness.provider_effect_boundary_ref
        and request.provider_effect_boundary_sha256
        == readiness.provider_effect_boundary_sha256
        and request.response_verifier_ref == readiness.response_verifier_ref
        and request.response_verifier_sha256 == readiness.response_verifier_sha256
        and request.freshness_attestor_ref == readiness.freshness_attestor_ref
        and request.freshness_attestor_sha256
        == readiness.freshness_attestor_sha256
        and request.field_device_validator_ref
        == readiness.field_device_validator_ref
        and request.field_device_validator_sha256
        == readiness.field_device_validator_sha256
        and request.fallback_plan_ref == readiness.fallback_plan_ref
        and request.fallback_plan_sha256 == readiness.fallback_plan_sha256
    )


def _live_provider_execution_invocation_matches_readiness(
    readiness: ProductionLiveProviderExecutorReadinessDecision,
    invocation: ProductionLiveProviderExecutorInvocationReceipt,
) -> bool:
    return (
        invocation.provider_executor_readiness_sha256 == readiness.sha256
        and invocation.provider_request_readiness_sha256
        == readiness.provider_request_readiness_sha256
        and invocation.provider_executor_manifest_sha256
        == readiness.provider_executor_manifest_sha256
        and invocation.connector_manifest_sha256 == readiness.connector_manifest_sha256
        and invocation.request_contract_sha256 == readiness.request_contract_sha256
        and invocation.gate_id == readiness.gate_id
        and invocation.connector_id == readiness.connector_id
        and invocation.source_observation_path == readiness.source_observation_path
        and invocation.route_scope_ref == readiness.route_scope_ref
        and invocation.provider_request_ref == readiness.provider_request_ref
        and invocation.provider_request_sha256 == readiness.provider_request_sha256
        and invocation.provider_effect_boundary_ref
        == readiness.provider_effect_boundary_ref
        and invocation.provider_effect_boundary_sha256
        == readiness.provider_effect_boundary_sha256
        and invocation.response_verifier_ref == readiness.response_verifier_ref
        and invocation.response_verifier_sha256 == readiness.response_verifier_sha256
        and invocation.freshness_attestor_ref == readiness.freshness_attestor_ref
        and invocation.freshness_attestor_sha256
        == readiness.freshness_attestor_sha256
        and invocation.field_device_validator_ref
        == readiness.field_device_validator_ref
        and invocation.field_device_validator_sha256
        == readiness.field_device_validator_sha256
        and invocation.fallback_plan_ref == readiness.fallback_plan_ref
        and invocation.fallback_plan_sha256 == readiness.fallback_plan_sha256
    )


def _live_provider_execution_request_sha256(
    request: ProductionLiveProviderExecutionRequest,
) -> str:
    return aggregate_sha256(
        [
            {
                "artifact": request.artifact_kind,
                "payload": request.model_dump(mode="json"),
                "runtime_ingest_performed": False,
                "safety_api_called": False,
                "phase1_l0_l4_state_mutated": False,
            }
        ]
    )


def _live_provider_response_matches_invocation(
    invocation: ProductionLiveProviderExecutorInvocationReceipt,
    receipt: ProductionLiveProviderResponseReceipt,
) -> bool:
    return (
        receipt.provider_executor_invocation_sha256 == invocation.sha256
        and receipt.provider_execution_ref == invocation.provider_execution_ref
        and receipt.provider_execution_sha256 == invocation.provider_execution_sha256
        and receipt.provider_request_readiness_sha256
        == invocation.provider_request_readiness_sha256
        and receipt.manifest_sha256 == invocation.connector_manifest_sha256
        and receipt.request_contract_sha256 == invocation.request_contract_sha256
        and receipt.gate_id == invocation.gate_id
        and receipt.connector_id == invocation.connector_id
        and receipt.source_observation_path == invocation.source_observation_path
        and receipt.route_scope_ref == invocation.route_scope_ref
        and receipt.provider_request_ref == invocation.provider_request_ref
        and receipt.provider_request_sha256 == invocation.provider_request_sha256
    )


def _live_provider_effect_receipt_sha256(
    receipt: ProductionLiveProviderEffectReceipt,
) -> str:
    return aggregate_sha256(
        [
            {
                "artifact": receipt.artifact_kind,
                "payload": receipt.model_dump(mode="json"),
                "runtime_ingest_performed": False,
                "safety_api_called": False,
            }
        ]
    )


def _live_provider_effect_matches_invocation(
    invocation: ProductionLiveProviderExecutorInvocationReceipt,
    receipt: ProductionLiveProviderEffectReceipt,
) -> bool:
    return (
        receipt.provider_executor_invocation_sha256 == invocation.sha256
        and receipt.provider_executor_readiness_sha256
        == invocation.provider_executor_readiness_sha256
        and receipt.provider_request_readiness_sha256
        == invocation.provider_request_readiness_sha256
        and receipt.provider_executor_manifest_sha256
        == invocation.provider_executor_manifest_sha256
        and receipt.connector_manifest_sha256 == invocation.connector_manifest_sha256
        and receipt.request_contract_sha256 == invocation.request_contract_sha256
        and receipt.gate_id == invocation.gate_id
        and receipt.connector_id == invocation.connector_id
        and receipt.source_observation_path == invocation.source_observation_path
        and receipt.route_scope_ref == invocation.route_scope_ref
        and receipt.provider_request_ref == invocation.provider_request_ref
        and receipt.provider_request_sha256 == invocation.provider_request_sha256
        and receipt.provider_execution_ref == invocation.provider_execution_ref
        and receipt.provider_execution_sha256 == invocation.provider_execution_sha256
    )


def _live_provider_effect_evidence_present(
    receipt: ProductionLiveProviderEffectReceipt,
) -> bool:
    evidence_present = bool(
        receipt.provider_evidence_ref
        and receipt.provider_evidence_sha256
        and receipt.freshness_attestation_ref
        and receipt.freshness_attestation_sha256
    )
    if receipt.gate_id == "environment_threat_gate":
        return evidence_present and bool(receipt.current_observation_ref)
    return evidence_present


def _live_provider_response_matches_readiness(
    readiness: ProductionLiveProviderRequestReadinessReceipt,
    receipt: ProductionLiveProviderResponseReceipt,
) -> bool:
    return (
        receipt.provider_request_readiness_sha256 == readiness.sha256
        and receipt.manifest_sha256 == readiness.manifest_sha256
        and receipt.request_contract_sha256 == readiness.request_contract_sha256
        and receipt.gate_id == readiness.gate_id
        and receipt.connector_id == readiness.connector_id
        and receipt.source_observation_path == readiness.source_observation_path
        and receipt.route_scope_ref == readiness.route_scope_ref
        and receipt.provider_request_ref == readiness.provider_request_ref
        and receipt.provider_request_sha256 == readiness.provider_request_sha256
        and receipt.freshness_requirement_minutes
        == readiness.freshness_requirement_minutes
    )


def _live_freshness_attestation_matches_response(
    freshness: ProductionLiveFreshnessAttestationReceipt,
    response: ProductionLiveProviderResponseReceipt,
    response_sha256: str,
) -> bool:
    return (
        freshness.gate_id == response.gate_id
        and freshness.route_scope_ref == response.route_scope_ref
        and (
            freshness.source_observation_path is None
            or freshness.source_observation_path == response.source_observation_path
        )
        and (
            freshness.provider_request_ref is None
            or freshness.provider_request_ref == response.provider_request_ref
        )
        and (
            freshness.provider_response_receipt_sha256 is None
            or freshness.provider_response_receipt_sha256 == response_sha256
        )
        and (
            freshness.provider_evidence_ref is None
            or freshness.provider_evidence_ref == response.provider_evidence_ref
        )
        and (
            freshness.provider_evidence_sha256 is None
            or freshness.provider_evidence_sha256 == response.provider_evidence_sha256
        )
        and freshness.freshness_requirement_minutes
        == response.freshness_requirement_minutes
    )


def _live_freshness_attestation_decision_matches_response(
    freshness: ProductionLiveFreshnessAttestationDecision,
    response: ProductionLiveProviderResponseReceipt,
    response_sha256: str,
) -> bool:
    return (
        freshness.gate_id == response.gate_id
        and freshness.route_scope_ref == response.route_scope_ref
        and (
            freshness.source_observation_path is None
            or freshness.source_observation_path == response.source_observation_path
        )
        and (
            freshness.provider_request_ref is None
            or freshness.provider_request_ref == response.provider_request_ref
        )
        and (
            freshness.provider_response_receipt_sha256 is None
            or freshness.provider_response_receipt_sha256 == response_sha256
        )
        and (
            freshness.provider_evidence_ref is None
            or freshness.provider_evidence_ref == response.provider_evidence_ref
        )
        and (
            freshness.provider_evidence_sha256 is None
            or freshness.provider_evidence_sha256 == response.provider_evidence_sha256
        )
        and freshness.freshness_requirement_minutes
        == response.freshness_requirement_minutes
    )


def _live_field_device_validation_matches_response(
    validation: ProductionLiveFieldDeviceValidationReceipt,
    response: ProductionLiveProviderResponseReceipt,
    response_sha256: str,
) -> bool:
    return (
        validation.gate_id == response.gate_id
        and validation.route_scope_ref == response.route_scope_ref
        and (
            validation.source_observation_path is None
            or validation.source_observation_path == response.source_observation_path
        )
        and (
            validation.provider_request_ref is None
            or validation.provider_request_ref == response.provider_request_ref
        )
        and (
            validation.provider_response_receipt_sha256 is None
            or validation.provider_response_receipt_sha256 == response_sha256
        )
        and (
            validation.current_observation_ref is None
            or response.current_observation_ref is None
            or validation.current_observation_ref == response.current_observation_ref
        )
    )


def _live_field_device_validation_decision_matches_response(
    validation: ProductionLiveFieldDeviceValidationDecision,
    response: ProductionLiveProviderResponseReceipt,
    response_sha256: str,
) -> bool:
    return (
        validation.gate_id == response.gate_id
        and validation.route_scope_ref == response.route_scope_ref
        and (
            validation.source_observation_path is None
            or validation.source_observation_path == response.source_observation_path
        )
        and (
            validation.provider_request_ref is None
            or validation.provider_request_ref == response.provider_request_ref
        )
        and (
            validation.provider_response_receipt_sha256 is None
            or validation.provider_response_receipt_sha256 == response_sha256
        )
        and (
            validation.current_observation_ref is None
            or response.current_observation_ref is None
            or validation.current_observation_ref == response.current_observation_ref
        )
    )


def _provider_response_with_attestations(
    receipt: ProductionLiveProviderResponseReceipt,
    freshness: ProductionLiveFreshnessAttestationDecision | None,
    validation: ProductionLiveFieldDeviceValidationDecision | None,
) -> ProductionLiveProviderResponseReceipt:
    update: dict[str, Any] = {}
    if freshness is not None:
        update.update(
            {
                "freshness_attestation_ref": (
                    freshness.freshness_attestation_ref
                    or receipt.freshness_attestation_ref
                ),
                "freshness_attestation_sha256": (
                    freshness.freshness_attestation_sha256
                    or receipt.freshness_attestation_sha256
                ),
                "source_age_minutes": freshness.source_age_minutes,
                "freshness_requirement_minutes": (
                    freshness.freshness_requirement_minutes
                ),
            }
        )
    if validation is None:
        return receipt.model_copy(update=update) if update else receipt
    update.update(
        {
            "current_observation_ref": (
                receipt.current_observation_ref or validation.current_observation_ref
            ),
            "field_attestation_ref": (
                validation.field_attestation_ref or receipt.field_attestation_ref
            ),
            "device_evidence_ref": (
                validation.device_evidence_ref or receipt.device_evidence_ref
            ),
        }
    )
    return receipt.model_copy(
        update=update,
    )


def _live_provider_response_evidence_present(
    receipt: ProductionLiveProviderResponseReceipt,
) -> bool:
    evidence_present = bool(
        receipt.provider_evidence_ref
        and receipt.provider_evidence_sha256
    )
    if receipt.gate_id == "environment_threat_gate":
        return evidence_present and bool(receipt.current_observation_ref)
    return evidence_present


def _live_observation_from_provider_response(
    receipt: ProductionLiveProviderResponseReceipt,
) -> ProductionLiveWeatherObservation | ProductionLiveEnvironmentThreatObservation:
    evidence_refs = _unique_refs(
        [
            receipt.provider_evidence_ref,
            receipt.current_observation_ref,
            receipt.provider_request_ref,
            receipt.provider_execution_ref,
            receipt.freshness_attestation_ref,
            receipt.route_scope_ref,
            receipt.field_attestation_ref,
            receipt.device_evidence_ref,
            *receipt.evidence_refs,
        ]
    )
    if receipt.gate_id == "weather_gate":
        return ProductionLiveWeatherObservation(
            source_provider=receipt.source_provider,
            source_path=receipt.source_path,
            event_id=f"weather_gate:provider-response:{receipt.provider_request_sha256[:12]}",
            observed_at_offset_s=receipt.observed_at_offset_s,
            warning_level=receipt.warning_level,
            warning_type=receipt.warning_type,
            wind_risk=receipt.wind_risk,
            rain_risk=receipt.rain_risk,
            lightning_risk=receipt.lightning_risk,
            source_age_minutes=receipt.source_age_minutes,
            provider_dataset_ids=receipt.provider_dataset_ids,
            provider_evidence_ref=receipt.provider_evidence_ref,
            provider_request_ref=receipt.provider_request_ref,
            provider_request_sha256=receipt.provider_request_sha256,
            freshness_attestation_ref=receipt.freshness_attestation_ref,
            route_scope_ref=receipt.route_scope_ref,
            field_attestation_ref=receipt.field_attestation_ref,
            route_pressure_review_required=receipt.route_pressure_review_required,
            route_context=receipt.route_context,
            evidence_refs=evidence_refs,
            confidence=receipt.confidence,
        )
    return ProductionLiveEnvironmentThreatObservation(
        source_provider=receipt.source_provider,
        source_path=receipt.source_path,
        event_id=(
            "environment_threat_gate:provider-response:"
            f"{receipt.provider_request_sha256[:12]}"
        ),
        observed_at_offset_s=receipt.observed_at_offset_s,
        threat_type=receipt.threat_type or "provider_reported_environment_threat",
        passability=receipt.passability,
        immediacy=receipt.immediacy,
        route_blocked=receipt.route_blocked,
        safe_bypass_known=receipt.safe_bypass_known,
        current_observation_ref=(
            receipt.current_observation_ref or receipt.provider_evidence_ref
        ),
        provider_request_ref=receipt.provider_request_ref,
        provider_request_sha256=receipt.provider_request_sha256,
        freshness_attestation_ref=receipt.freshness_attestation_ref,
        route_scope_ref=receipt.route_scope_ref,
        provider_evidence_ref=receipt.provider_evidence_ref,
        field_attestation_ref=receipt.field_attestation_ref,
        device_evidence_ref=receipt.device_evidence_ref,
        route_pressure_review_required=(
            receipt.route_pressure_review_required or receipt.route_blocked
        ),
        route_context=receipt.route_context,
        evidence_refs=evidence_refs,
        confidence=receipt.confidence,
    )


def _prepared_live_observation_sha256(
    observation: ProductionLiveWeatherObservation | ProductionLiveEnvironmentThreatObservation,
) -> str:
    artifact = (
        "production_live_weather_observation"
        if isinstance(observation, ProductionLiveWeatherObservation)
        else "production_live_environment_threat_observation"
    )
    return _live_observation_sha256(
        observation.model_dump(mode="json"),
        artifact=artifact,
    )


def _provider_request_lineage_mismatch(
    manifest: ProductionLiveProviderConnectorManifest,
    request: ProductionLiveProviderRequestContract,
) -> bool:
    return any(
        (
            request.gate_id != manifest.gate_id,
            request.connector_id != manifest.connector_id,
            request.source_provider != manifest.source_provider,
            request.source_path != manifest.source_path,
            request.route_scope_ref != manifest.route_scope_ref,
            request.freshness_requirement_minutes
            != manifest.freshness_requirement_minutes,
        )
    )


def _unique_refs(values: list[str | None]) -> list[str]:
    seen: set[str] = set()
    refs: list[str] = []
    for value in values:
        if value is None or not value:
            continue
        if value not in seen:
            seen.add(value)
            refs.append(value)
    return refs
