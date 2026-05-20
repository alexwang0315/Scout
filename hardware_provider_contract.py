from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class HardwareProviderContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HardwareProviderDomain(StrEnum):
    GNSS = "gnss"
    IMU = "imu"
    BATTERY = "battery"
    BLE = "ble"
    CELLULAR = "cellular"


class HardwareProviderStatus(StrEnum):
    AVAILABLE = "available"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


REQUIRED_PROVIDER_DOMAINS = frozenset(
    {
        HardwareProviderDomain.GNSS,
        HardwareProviderDomain.IMU,
        HardwareProviderDomain.BATTERY,
        HardwareProviderDomain.BLE,
        HardwareProviderDomain.CELLULAR,
    }
)


class HardwareProviderBoundary(HardwareProviderContractModel):
    fixture_backed: Literal[True] = True
    read_only: Literal[True] = True
    provider_control_allowed: Literal[False] = False
    live_io_allowed: Literal[False] = False
    network_calls_allowed: Literal[False] = False
    safety_mutation_calls_allowed: Literal[False] = False
    phase1_safety_decision_mutation_allowed: Literal[False] = False
    incident_store_write_allowed: Literal[False] = False
    observed_fact_write_allowed: Literal[False] = False
    brain_write_allowed: Literal[False] = False
    outbound_send_allowed: Literal[False] = False
    endpoint_calls: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_no_endpoint_calls(self) -> "HardwareProviderBoundary":
        if self.endpoint_calls:
            raise ValueError("hardware provider contract must not call endpoints")
        return self


class HardwareProviderEvidenceField(HardwareProviderContractModel):
    field_name: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_.:-]+$")
    description: str = Field(min_length=1)
    unit: str | None = None
    required: bool = True


class HardwareProviderEvidenceContract(HardwareProviderContractModel):
    source_payload_fields: list[str] = Field(min_length=1)
    normalized_fields: list[HardwareProviderEvidenceField] = Field(min_length=1)
    writes_incident_store: Literal[False] = False
    writes_observed_fact: Literal[False] = False
    writes_brain: Literal[False] = False
    phase1_safety_decision_change_allowed: Literal[False] = False


class HardwareProviderDegradedBehavior(HardwareProviderContractModel):
    trigger: str = Field(min_length=1)
    projected_status: HardwareProviderStatus
    degradation_code: str = Field(min_length=1, pattern=r"^[a-z0-9_.:-]+$")
    runtime_behavior: Literal["continue_with_provider_status_projection"] = (
        "continue_with_provider_status_projection"
    )
    phase1_behavior: Literal["no_phase1_safety_decision_change"] = (
        "no_phase1_safety_decision_change"
    )
    evidence_behavior: Literal["read_only_manifest_status_only"] = (
        "read_only_manifest_status_only"
    )
    operator_guidance: str = Field(min_length=1)
    blocks_runtime_start: Literal[False] = False
    controls_provider: Literal[False] = False
    calls_safety_mutation: Literal[False] = False
    writes_incident_store: Literal[False] = False
    writes_observed_fact: Literal[False] = False
    writes_brain: Literal[False] = False
    sends_outbound: Literal[False] = False

    @model_validator(mode="after")
    def reject_available_projection(self) -> "HardwareProviderDegradedBehavior":
        if self.projected_status == HardwareProviderStatus.AVAILABLE:
            raise ValueError("degraded behavior must project degraded or unavailable status")
        return self


class HardwareProviderManifestEntry(HardwareProviderContractModel):
    provider_ref: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_.:-]+$")
    domain: HardwareProviderDomain
    display_name: str = Field(min_length=1)
    provider_mode: Literal["fixture"] = "fixture"
    transport: Literal["fixture"] = "fixture"
    status: HardwareProviderStatus
    required_for_runtime_start: Literal[False] = False
    required_permissions: list[str] = Field(default_factory=list)
    expected_sample_rate_hz: float | None = Field(default=None, gt=0)
    expected_message_rate_per_minute: float | None = Field(default=None, gt=0)
    live_io_allowed: Literal[False] = False
    controls_provider: Literal[False] = False
    polling_allowed: Literal[False] = False
    evidence: HardwareProviderEvidenceContract
    degraded_behaviors: list[HardwareProviderDegradedBehavior] = Field(min_length=1)

    @model_validator(mode="after")
    def enforce_status_has_projection(self) -> "HardwareProviderManifestEntry":
        if self.status == HardwareProviderStatus.AVAILABLE:
            return self
        projected_statuses = {behavior.projected_status for behavior in self.degraded_behaviors}
        if self.status not in projected_statuses:
            raise ValueError("provider status must have a matching degraded behavior projection")
        return self


class HardwareProviderContractManifest(HardwareProviderContractModel):
    artifact_kind: Literal["hardware_provider_contract_manifest"] = (
        "hardware_provider_contract_manifest"
    )
    contract_version: Literal["hardware_provider_contract.v0"] = (
        "hardware_provider_contract.v0"
    )
    status: Literal["fixture_contract_ready_not_connected"] = (
        "fixture_contract_ready_not_connected"
    )
    manifest_id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_.:-]+$")
    source_path: str = Field(min_length=1)
    boundary: HardwareProviderBoundary = Field(default_factory=HardwareProviderBoundary)
    providers: list[HardwareProviderManifestEntry] = Field(min_length=1)

    @model_validator(mode="after")
    def enforce_manifest_contract(self) -> "HardwareProviderContractManifest":
        provider_refs = [provider.provider_ref for provider in self.providers]
        duplicate_refs = sorted(
            provider_ref
            for provider_ref in set(provider_refs)
            if provider_refs.count(provider_ref) > 1
        )
        if duplicate_refs:
            raise ValueError(f"duplicate provider refs: {', '.join(duplicate_refs)}")

        domains = {provider.domain for provider in self.providers}
        missing_domains = REQUIRED_PROVIDER_DOMAINS - domains
        if missing_domains:
            missing = ", ".join(sorted(domain.value for domain in missing_domains))
            raise ValueError(f"missing required provider domains: {missing}")

        for provider in self.providers:
            if provider.required_permissions:
                raise ValueError("fixture provider contract must not require live permissions")
            if provider.evidence.writes_incident_store:
                raise ValueError("provider evidence must not write incident store")
            if provider.evidence.writes_observed_fact:
                raise ValueError("provider evidence must not write observed facts")
            if provider.evidence.writes_brain:
                raise ValueError("provider evidence must not write brain")
            if provider.evidence.phase1_safety_decision_change_allowed:
                raise ValueError("provider evidence must not change Phase 1 safety decisions")
        return self

    def to_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n"


class HardwareProviderDegradedProjection(HardwareProviderContractModel):
    provider_ref: str
    domain: HardwareProviderDomain
    status: HardwareProviderStatus
    degradation_codes: list[str]
    runtime_behavior: Literal["continue_with_provider_status_projection"] = (
        "continue_with_provider_status_projection"
    )
    phase1_behavior: Literal["no_phase1_safety_decision_change"] = (
        "no_phase1_safety_decision_change"
    )
    blocks_runtime_start: Literal[False] = False
    controls_provider: Literal[False] = False
    calls_safety_mutation: Literal[False] = False
    writes_incident_store: Literal[False] = False
    writes_observed_fact: Literal[False] = False
    writes_brain: Literal[False] = False
    sends_outbound: Literal[False] = False


class HardwareProviderContractCounts(HardwareProviderContractModel):
    provider_count: int
    required_domain_count: int
    available_provider_count: int
    degraded_provider_count: int
    unavailable_provider_count: int
    blocker_count: int


class HardwareProviderContractReport(HardwareProviderContractModel):
    artifact_kind: Literal["hardware_provider_contract_report"] = (
        "hardware_provider_contract_report"
    )
    manifest_id: str
    status: Literal["fixture_contract_ready", "fixture_contract_ready_degraded"]
    runtime_start_allowed: Literal[True] = True
    phase1_safety_decision_unchanged: Literal[True] = True
    degraded_providers: list[HardwareProviderDegradedProjection] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    boundary: HardwareProviderBoundary = Field(default_factory=HardwareProviderBoundary)
    counts: HardwareProviderContractCounts


def load_hardware_provider_contract_manifest(
    path: Path | str,
) -> HardwareProviderContractManifest:
    return HardwareProviderContractManifest.model_validate_json(
        Path(path).read_text(encoding="utf-8")
    )


def build_hardware_provider_contract_report(
    manifest: HardwareProviderContractManifest,
) -> HardwareProviderContractReport:
    degraded_providers = [
        _degraded_projection(provider)
        for provider in manifest.providers
        if provider.status != HardwareProviderStatus.AVAILABLE
    ]
    available_count = sum(
        1 for provider in manifest.providers if provider.status == HardwareProviderStatus.AVAILABLE
    )
    degraded_count = sum(
        1 for provider in manifest.providers if provider.status == HardwareProviderStatus.DEGRADED
    )
    unavailable_count = sum(
        1 for provider in manifest.providers if provider.status == HardwareProviderStatus.UNAVAILABLE
    )
    return HardwareProviderContractReport(
        manifest_id=manifest.manifest_id,
        status=(
            "fixture_contract_ready_degraded"
            if degraded_providers
            else "fixture_contract_ready"
        ),
        degraded_providers=degraded_providers,
        boundary=manifest.boundary,
        counts=HardwareProviderContractCounts(
            provider_count=len(manifest.providers),
            required_domain_count=len(REQUIRED_PROVIDER_DOMAINS),
            available_provider_count=available_count,
            degraded_provider_count=degraded_count,
            unavailable_provider_count=unavailable_count,
            blocker_count=0,
        ),
    )


def _degraded_projection(
    provider: HardwareProviderManifestEntry,
) -> HardwareProviderDegradedProjection:
    matching_behaviors = [
        behavior
        for behavior in provider.degraded_behaviors
        if behavior.projected_status == provider.status
    ]
    return HardwareProviderDegradedProjection(
        provider_ref=provider.provider_ref,
        domain=provider.domain,
        status=provider.status,
        degradation_codes=[behavior.degradation_code for behavior in matching_behaviors],
    )
