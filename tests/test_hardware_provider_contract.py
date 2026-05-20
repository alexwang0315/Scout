from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

import hardware_provider_contract
from hardware_provider_contract import (
    REQUIRED_PROVIDER_DOMAINS,
    HardwareProviderContractManifest,
    HardwareProviderDomain,
    HardwareProviderStatus,
    build_hardware_provider_contract_report,
    load_hardware_provider_contract_manifest,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "hardware" / "provider_contract.example.json"


def load_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def test_provider_contract_fixture_defines_required_fixture_backed_providers() -> None:
    manifest = load_hardware_provider_contract_manifest(FIXTURE_PATH)

    provider_domains = {provider.domain for provider in manifest.providers}
    provider_refs = {provider.provider_ref for provider in manifest.providers}

    assert manifest.artifact_kind == "hardware_provider_contract_manifest"
    assert manifest.status == "fixture_contract_ready_not_connected"
    assert provider_domains == REQUIRED_PROVIDER_DOMAINS
    assert provider_refs == {
        "provider.gnss.fixture.v0",
        "provider.imu.fixture.v0",
        "provider.battery.fixture.v0",
        "provider.ble.fixture.v0",
        "provider.cellular.fixture.v0",
    }
    assert all(provider.provider_mode == "fixture" for provider in manifest.providers)
    assert all(provider.transport == "fixture" for provider in manifest.providers)
    assert all(provider.required_for_runtime_start is False for provider in manifest.providers)
    assert all(provider.live_io_allowed is False for provider in manifest.providers)
    assert all(provider.controls_provider is False for provider in manifest.providers)
    assert all(provider.polling_allowed is False for provider in manifest.providers)


def test_provider_contract_report_keeps_degraded_behavior_read_only() -> None:
    manifest = load_hardware_provider_contract_manifest(FIXTURE_PATH)

    report = build_hardware_provider_contract_report(manifest)

    degraded = {provider.provider_ref: provider for provider in report.degraded_providers}
    assert report.status == "fixture_contract_ready_degraded"
    assert report.runtime_start_allowed is True
    assert report.phase1_safety_decision_unchanged is True
    assert report.blockers == []
    assert report.counts.provider_count == 5
    assert report.counts.available_provider_count == 2
    assert report.counts.degraded_provider_count == 2
    assert report.counts.unavailable_provider_count == 1
    assert set(degraded) == {
        "provider.battery.fixture.v0",
        "provider.ble.fixture.v0",
        "provider.cellular.fixture.v0",
    }
    assert degraded["provider.battery.fixture.v0"].status == HardwareProviderStatus.DEGRADED
    assert degraded["provider.ble.fixture.v0"].status == HardwareProviderStatus.UNAVAILABLE
    assert degraded["provider.cellular.fixture.v0"].degradation_codes == ["cellular.no_service"]
    assert all(provider.blocks_runtime_start is False for provider in degraded.values())
    assert all(provider.controls_provider is False for provider in degraded.values())
    assert all(provider.calls_safety_mutation is False for provider in degraded.values())
    assert all(provider.writes_incident_store is False for provider in degraded.values())
    assert all(provider.writes_observed_fact is False for provider in degraded.values())
    assert all(provider.writes_brain is False for provider in degraded.values())
    assert all(provider.sends_outbound is False for provider in degraded.values())


def test_provider_contract_boundary_rejects_mutation_and_live_io() -> None:
    payload = load_fixture()
    payload["boundary"]["outbound_send_allowed"] = True

    with pytest.raises(ValidationError):
        HardwareProviderContractManifest.model_validate(payload)

    payload = load_fixture()
    payload["providers"][0]["live_io_allowed"] = True

    with pytest.raises(ValidationError):
        HardwareProviderContractManifest.model_validate(payload)

    payload = load_fixture()
    payload["providers"][2]["degraded_behaviors"][0]["calls_safety_mutation"] = True

    with pytest.raises(ValidationError):
        HardwareProviderContractManifest.model_validate(payload)


def test_provider_contract_rejects_missing_domain_and_duplicate_refs() -> None:
    payload = load_fixture()
    payload["providers"] = [
        provider
        for provider in payload["providers"]
        if provider["domain"] != HardwareProviderDomain.CELLULAR
    ]

    with pytest.raises(ValidationError, match="missing required provider domains"):
        HardwareProviderContractManifest.model_validate(payload)

    payload = load_fixture()
    payload["providers"][1]["provider_ref"] = payload["providers"][0]["provider_ref"]

    with pytest.raises(ValidationError, match="duplicate provider refs"):
        HardwareProviderContractManifest.model_validate(payload)


def test_provider_contract_source_has_no_runtime_side_effect_imports() -> None:
    manifest = load_hardware_provider_contract_manifest(FIXTURE_PATH)
    report = build_hardware_provider_contract_report(manifest)
    source = inspect.getsource(hardware_provider_contract)
    serialized = json.dumps(
        [manifest.model_dump(mode="json"), report.model_dump(mode="json")],
        sort_keys=True,
    )

    assert manifest.boundary.provider_control_allowed is False
    assert manifest.boundary.safety_mutation_calls_allowed is False
    assert manifest.boundary.incident_store_write_allowed is False
    assert manifest.boundary.observed_fact_write_allowed is False
    assert manifest.boundary.brain_write_allowed is False
    assert manifest.boundary.outbound_send_allowed is False
    assert '"outbound_send_allowed": true' not in serialized
    assert "/safety/" not in source
    for forbidden in (
        "from safety_api",
        "import safety_api",
        "from incident_store",
        "import incident_store",
        "phase2_brain",
        "mock_outbound_transport",
        "requests.",
        "import requests",
        "httpx.",
        "import httpx",
        "urllib",
        "FastAPI",
    ):
        assert forbidden not in source
