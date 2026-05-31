from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any, Literal

from scout_energy_models import (
    ScoutEnergyBoundary,
    ScoutEnergyDataQuality,
    ScoutEnergyPrivacy,
    aggregate_sha256,
    sha256_file,
)
from scout_wearable_raw_importers import (
    ProviderApiFixture,
    write_sanitized_import_batch_from_provider_api_fixture,
)
from scout_wearable_adapters import write_normalized_wearable_imports
from scout_wearable_validator import assert_valid_wearable_activity_summary_contract


ProviderLiveTransportProvider = Literal["apple_healthkit_live", "garmin_health_api_live"]
ProviderLiveExecutorKind = Literal["apple_healthkit_local_bridge", "garmin_health_api_client"]
ProviderLiveConnectorKind = Literal[
    "apple_healthkit_local_bridge_connector",
    "garmin_health_api_connector",
]

_APPLE_SCOPE_MAP = {
    "HKWorkoutType": "workout:read",
    "HKQuantityTypeIdentifierHeartRate": "heart_rate:read",
    "HKQuantityTypeIdentifierRestingHeartRate": "heart_rate:read",
    "HKQuantityTypeIdentifierHeartRateVariabilitySDNN": "hrv:read",
    "workout:read": "workout:read",
    "heart_rate:read": "heart_rate:read",
    "hrv:read": "hrv:read",
}

_GARMIN_SCOPE_ALLOWLIST = {
    "activity:read",
    "heart_rate:read",
    "body_energy:read",
    "stress:read",
}

_PROVIDER_SUPPORTED_CAPABILITIES = {
    "apple_healthkit_live": [
        "activity_summary_import",
        "heart_rate_samples",
        "live_frame_stream",
    ],
    "garmin_health_api_live": [
        "activity_summary_import",
        "heart_rate_samples",
        "live_frame_stream",
        "provider_body_energy_source_values",
    ],
}

_PROVIDER_EXECUTOR_KINDS = {
    "apple_healthkit_live": "apple_healthkit_local_bridge",
    "garmin_health_api_live": "garmin_health_api_client",
}

_PROVIDER_CONNECTOR_KINDS = {
    "apple_healthkit_live": "apple_healthkit_local_bridge_connector",
    "garmin_health_api_live": "garmin_health_api_connector",
}


def build_provider_live_transport_preflight(
    *,
    provider: ProviderLiveTransportProvider,
    explicit_consent: bool,
    account_ref: str,
    auth_token_ref: str,
    scopes: list[str],
    requested_capabilities: list[str],
    device_ref: str | None = None,
    source_path: str | None = None,
    network_request_performed: bool = False,
    real_provider_api_called: bool = False,
    runtime_ingest_performed: bool = False,
) -> dict[str, Any]:
    if provider not in _PROVIDER_SUPPORTED_CAPABILITIES:
        raise ValueError(f"provider live transport is not supported: {provider}")
    if not explicit_consent:
        raise ValueError("explicit consent is required before provider live transport preflight")
    if not account_ref.strip():
        raise ValueError("account ref is required before provider live transport preflight")
    if not auth_token_ref.strip():
        raise ValueError("auth token ref is required before provider live transport preflight")
    if not scopes:
        raise ValueError("at least one provider scope is required before provider live transport preflight")
    if not requested_capabilities:
        raise ValueError("at least one capability flag is required before provider live transport preflight")
    _assert_preflight_only(
        network_request_performed=network_request_performed,
        real_provider_api_called=real_provider_api_called,
        runtime_ingest_performed=runtime_ingest_performed,
    )

    scope_review = _normalize_provider_scopes(provider, scopes)
    capability_review = _review_capabilities(
        provider,
        normalized_scopes=scope_review["normalized_scopes"],
        requested_capabilities=requested_capabilities,
    )
    resolved_source_path = source_path or f"provider-live-preflight://{provider}"
    data_quality = ScoutEnergyDataQuality(
        heart_rate_confidence="low",
        gps_confidence="low",
        provider_value_confidence="low",
        limitations=[
            "provider live transport preflight validates consent, scopes, and capability flags only",
            "no network request, real provider API call, or runtime ingest is performed",
            "token, account, and device refs are represented only by sha256 digests",
        ],
    )
    privacy = ScoutEnergyPrivacy()
    boundary = ScoutEnergyBoundary()
    source_fingerprint = aggregate_sha256(
        [
            {
                "provider": provider,
                "source_path": resolved_source_path,
                "account_ref_sha256": _sha256_text(account_ref),
                "device_ref_sha256": _sha256_text(device_ref) if device_ref else None,
                "token_ref_sha256": _sha256_text(auth_token_ref),
                "normalized_scopes": scope_review["normalized_scopes"],
                "requested_capabilities": capability_review["requested_capabilities"],
                "transport_mode": "preflight_only",
            }
        ]
    )
    return {
        "artifact_kind": "scout_wearable_provider_live_transport_preflight",
        "artifact_version": "wearable_provider_live_transport_preflight.v1",
        "source_provider": provider,
        "source_path": resolved_source_path,
        "sha256": source_fingerprint,
        "authorization": {
            "provider": provider,
            "account_authorized": True,
            "explicit_consent": True,
            "account_ref_present": True,
            "account_ref_sha256": _sha256_text(account_ref),
            "device_ref_present": device_ref is not None and bool(device_ref.strip()),
            "device_ref_sha256": _sha256_text(device_ref) if device_ref else None,
            "token_value_exposed": False,
            "token_ref_sha256": _sha256_text(auth_token_ref),
            "normalized_scopes": scope_review["normalized_scopes"],
            "unsupported_scope_count": scope_review["unsupported_scope_count"],
        },
        "capability_review": capability_review,
        "transport": {
            "transport_mode": "preflight_only",
            "network_request_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "raw_payload_committed": False,
        },
        "data_quality": data_quality.model_dump(mode="json"),
        "privacy": privacy.model_dump(mode="json"),
        "boundary": boundary.model_dump(mode="json"),
        "mutation": {
            "source_file_mutated": False,
            "network_request_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "phase1_runtime_mutated": False,
            "safety_api_called": False,
            "raw_payload_committed": False,
            "raw_health_payload_shared": False,
            "raw_track_shared": False,
            "exact_timestamps_shared": False,
        },
    }


def write_provider_live_transport_preflight(
    *,
    provider: ProviderLiveTransportProvider,
    output_path: Path,
    explicit_consent: bool,
    account_ref: str,
    auth_token_ref: str,
    scopes: list[str],
    requested_capabilities: list[str],
    device_ref: str | None = None,
    source_path: str | None = None,
) -> dict[str, Any]:
    artifact = build_provider_live_transport_preflight(
        provider=provider,
        explicit_consent=explicit_consent,
        account_ref=account_ref,
        device_ref=device_ref,
        auth_token_ref=auth_token_ref,
        scopes=scopes,
        requested_capabilities=requested_capabilities,
        source_path=source_path,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "artifact_kind": "scout_wearable_provider_live_transport_preflight_result",
        "artifact_version": "wearable_provider_live_transport_preflight_result.v1",
        "source_provider": artifact["source_provider"],
        "source_path": artifact["source_path"],
        "sha256": artifact["sha256"],
        "preflight_path": str(output_path),
        "preflight": artifact,
        "data_quality": artifact["data_quality"],
        "privacy": artifact["privacy"],
        "boundary": artifact["boundary"],
        "mutation": {
            "preflight_artifact_written": True,
            "source_file_mutated": False,
            "network_request_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "phase1_runtime_mutated": False,
            "safety_api_called": False,
            "raw_payload_committed": False,
            "raw_health_payload_shared": False,
            "raw_track_shared": False,
            "exact_timestamps_shared": False,
        },
    }


def build_provider_live_credential_vault_reference(
    *,
    provider: ProviderLiveTransportProvider,
    explicit_consent: bool,
    vault_ref: str,
    account_ref: str,
    token_ref: str,
    scopes: list[str],
    capabilities: list[str],
    device_ref: str | None = None,
    source_path: str | None = None,
    credential_values_loaded: bool = False,
    credential_values_exposed: bool = False,
    vault_lookup_performed: bool = False,
    vault_write_performed: bool = False,
    network_request_performed: bool = False,
    real_provider_api_called: bool = False,
    runtime_ingest_performed: bool = False,
) -> dict[str, Any]:
    if provider not in _PROVIDER_SUPPORTED_CAPABILITIES:
        raise ValueError(f"provider credential vault reference is not supported: {provider}")
    if not explicit_consent:
        raise ValueError("explicit consent is required before provider credential vault reference")
    if not vault_ref.strip():
        raise ValueError("vault ref is required before provider credential vault reference")
    if not account_ref.strip():
        raise ValueError("account ref is required before provider credential vault reference")
    if not token_ref.strip():
        raise ValueError("token ref is required before provider credential vault reference")
    if not scopes:
        raise ValueError("at least one provider scope is required before provider credential vault reference")
    if not capabilities:
        raise ValueError("at least one capability flag is required before provider credential vault reference")
    _assert_credential_vault_reference_only(
        credential_values_loaded=credential_values_loaded,
        credential_values_exposed=credential_values_exposed,
        vault_lookup_performed=vault_lookup_performed,
        vault_write_performed=vault_write_performed,
        network_request_performed=network_request_performed,
        real_provider_api_called=real_provider_api_called,
        runtime_ingest_performed=runtime_ingest_performed,
    )

    scope_review = _normalize_provider_scopes(provider, scopes)
    capability_review = _review_capabilities(
        provider,
        normalized_scopes=scope_review["normalized_scopes"],
        requested_capabilities=capabilities,
    )
    if not capability_review["capability_flags_valid"]:
        raise ValueError("provider credential vault reference requires supported capabilities and scopes")
    resolved_source_path = source_path or f"provider-live-credential-vault-reference://{provider}"
    data_quality = ScoutEnergyDataQuality(
        heart_rate_confidence="low",
        gps_confidence="low",
        provider_value_confidence="low",
        limitations=[
            "credential vault reference records provider refs as sha256 digests only",
            "credential values are not loaded, exposed, looked up, or written",
            "no network request, real provider API call, or runtime ingest is performed",
        ],
    )
    privacy = ScoutEnergyPrivacy()
    boundary = ScoutEnergyBoundary()
    source_fingerprint = aggregate_sha256(
        [
            {
                "provider": provider,
                "source_path": resolved_source_path,
                "vault_ref_sha256": _sha256_text(vault_ref),
                "account_ref_sha256": _sha256_text(account_ref),
                "token_ref_sha256": _sha256_text(token_ref),
                "device_ref_sha256": _sha256_text(device_ref) if device_ref else None,
                "normalized_scopes": scope_review["normalized_scopes"],
                "allowed_capabilities": capability_review["allowed_capabilities"],
                "transport_mode": "credential_vault_reference_only",
            }
        ]
    )
    return {
        "artifact_kind": "scout_wearable_provider_live_credential_vault_reference",
        "artifact_version": "wearable_provider_live_credential_vault_reference.v1",
        "source_provider": provider,
        "source_path": resolved_source_path,
        "sha256": source_fingerprint,
        "credential_vault": {
            "provider": provider,
            "vault_ref_present": True,
            "vault_ref_sha256": _sha256_text(vault_ref),
            "account_ref_present": True,
            "account_ref_sha256": _sha256_text(account_ref),
            "token_ref_present": True,
            "token_ref_sha256": _sha256_text(token_ref),
            "device_ref_present": device_ref is not None and bool(device_ref.strip()),
            "device_ref_sha256": _sha256_text(device_ref) if device_ref else None,
            "credential_values_loaded": False,
            "credential_values_exposed": False,
            "vault_lookup_performed": False,
            "vault_write_performed": False,
        },
        "authorization": {
            "provider": provider,
            "explicit_consent": True,
            "normalized_scopes": scope_review["normalized_scopes"],
            "unsupported_scope_count": scope_review["unsupported_scope_count"],
            "requested_capabilities": capability_review["requested_capabilities"],
            "allowed_capabilities": capability_review["allowed_capabilities"],
        },
        "capability_review": capability_review,
        "transport": {
            "transport_mode": "credential_vault_reference_only",
            "credential_vault_reference_only": True,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "raw_response_committed": False,
        },
        "data_quality": data_quality.model_dump(mode="json"),
        "privacy": privacy.model_dump(mode="json"),
        "boundary": boundary.model_dump(mode="json"),
        "mutation": {
            "source_file_mutated": False,
            "vault_lookup_performed": False,
            "vault_write_performed": False,
            "credential_values_loaded": False,
            "credential_values_exposed": False,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "phase1_runtime_mutated": False,
            "safety_api_called": False,
            "raw_payload_committed": False,
            "raw_health_payload_shared": False,
            "raw_track_shared": False,
            "exact_timestamps_shared": False,
        },
    }


def write_provider_live_credential_vault_reference(
    *,
    provider: ProviderLiveTransportProvider,
    output_path: Path,
    explicit_consent: bool,
    vault_ref: str,
    account_ref: str,
    token_ref: str,
    scopes: list[str],
    capabilities: list[str],
    device_ref: str | None = None,
    source_path: str | None = None,
) -> dict[str, Any]:
    artifact = build_provider_live_credential_vault_reference(
        provider=provider,
        explicit_consent=explicit_consent,
        vault_ref=vault_ref,
        account_ref=account_ref,
        token_ref=token_ref,
        device_ref=device_ref,
        scopes=scopes,
        capabilities=capabilities,
        source_path=source_path,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "artifact_kind": "scout_wearable_provider_live_credential_vault_reference_result",
        "artifact_version": "wearable_provider_live_credential_vault_reference_result.v1",
        "source_provider": artifact["source_provider"],
        "source_path": artifact["source_path"],
        "sha256": artifact["sha256"],
        "credential_vault_reference_path": str(output_path),
        "credential_vault_reference": artifact,
        "data_quality": artifact["data_quality"],
        "privacy": artifact["privacy"],
        "boundary": artifact["boundary"],
        "mutation": {
            "credential_vault_reference_artifact_written": True,
            "source_file_mutated": False,
            "vault_lookup_performed": False,
            "vault_write_performed": False,
            "credential_values_loaded": False,
            "credential_values_exposed": False,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "phase1_runtime_mutated": False,
            "safety_api_called": False,
            "raw_payload_committed": False,
            "raw_health_payload_shared": False,
            "raw_track_shared": False,
            "exact_timestamps_shared": False,
        },
    }


def load_provider_live_credential_vault_reference(
    credential_vault_reference_path: Path,
) -> dict[str, Any]:
    payload = json.loads(credential_vault_reference_path.read_text(encoding="utf-8"))
    if payload.get("artifact_kind") != "scout_wearable_provider_live_credential_vault_reference":
        raise ValueError("provider live credential vault reference artifact is required")
    return payload


def assert_provider_live_credential_vault_reference_safe(
    credential_vault_reference: dict[str, Any],
) -> None:
    credential_vault = credential_vault_reference.get("credential_vault", {})
    if (
        not credential_vault.get("vault_ref_sha256")
        or not credential_vault.get("account_ref_sha256")
        or not credential_vault.get("token_ref_sha256")
        or credential_vault.get("credential_values_loaded")
        or credential_vault.get("credential_values_exposed")
        or credential_vault.get("vault_lookup_performed")
        or credential_vault.get("vault_write_performed")
    ):
        raise ValueError("credential vault reference must contain digests only")
    authorization = credential_vault_reference.get("authorization", {})
    if not authorization.get("explicit_consent"):
        raise ValueError("credential vault reference requires explicit consent")
    if not credential_vault_reference.get("capability_review", {}).get("capability_flags_valid"):
        raise ValueError("credential vault reference requires valid capability flags")
    transport = credential_vault_reference.get("transport", {})
    if (
        transport.get("transport_mode") != "credential_vault_reference_only"
        or transport.get("network_request_performed")
        or transport.get("network_sync_performed")
        or transport.get("remote_upload_allowed")
        or transport.get("remote_upload_performed")
        or transport.get("real_provider_api_called")
        or transport.get("runtime_ingest_performed")
    ):
        raise ValueError("credential vault reference requires local-only transport")
    privacy = credential_vault_reference.get("privacy", {})
    if privacy.get("raw_health_payload_shared") or privacy.get("raw_track_shared") or privacy.get("exact_timestamps_shared"):
        raise ValueError("credential vault reference requires sanitized privacy")
    boundary = credential_vault_reference.get("boundary", {})
    if boundary.get("medical_diagnosis") or boundary.get("phase1_runtime_safety_truth"):
        raise ValueError("credential vault reference cannot use medical or Phase 1 safety truth")


def build_provider_live_connector_reference(
    *,
    provider: ProviderLiveTransportProvider,
    explicit_consent: bool,
    connector_kind: ProviderLiveConnectorKind,
    connector_ref: str,
    connector_version: str,
    supported_capabilities: list[str],
    connector_binary_ref: str | None = None,
    source_path: str | None = None,
    connector_process_started: bool = False,
    connector_health_check_performed: bool = False,
    connector_live_request_performed: bool = False,
    credential_values_loaded: bool = False,
    credential_values_exposed: bool = False,
    network_request_performed: bool = False,
    real_provider_api_called: bool = False,
    runtime_ingest_performed: bool = False,
) -> dict[str, Any]:
    if provider not in _PROVIDER_SUPPORTED_CAPABILITIES:
        raise ValueError(f"provider connector reference is not supported: {provider}")
    expected_kind = _PROVIDER_CONNECTOR_KINDS[provider]
    if connector_kind != expected_kind:
        raise ValueError(f"provider connector kind must be {expected_kind} for {provider}")
    if not explicit_consent:
        raise ValueError("explicit consent is required before provider connector reference")
    if not connector_ref.strip():
        raise ValueError("connector ref is required before provider connector reference")
    if not connector_version.strip():
        raise ValueError("connector version is required before provider connector reference")
    if not supported_capabilities:
        raise ValueError("at least one capability flag is required before provider connector reference")
    _assert_connector_reference_only(
        connector_process_started=connector_process_started,
        connector_health_check_performed=connector_health_check_performed,
        connector_live_request_performed=connector_live_request_performed,
        credential_values_loaded=credential_values_loaded,
        credential_values_exposed=credential_values_exposed,
        network_request_performed=network_request_performed,
        real_provider_api_called=real_provider_api_called,
        runtime_ingest_performed=runtime_ingest_performed,
    )

    capability_review = _review_connector_capabilities(
        provider,
        supported_capabilities=supported_capabilities,
    )
    if not capability_review["capability_flags_valid"]:
        raise ValueError("provider connector reference requires supported capabilities")
    resolved_source_path = source_path or f"provider-live-connector-reference://{provider}"
    data_quality = ScoutEnergyDataQuality(
        heart_rate_confidence="low",
        gps_confidence="low",
        provider_value_confidence="low",
        limitations=[
            "provider connector reference records local connector refs as sha256 digests only",
            "connector process is not started and no connector health check is performed",
            "no credential values, network request, real provider API call, or runtime ingest are used",
        ],
    )
    privacy = ScoutEnergyPrivacy()
    boundary = ScoutEnergyBoundary()
    source_fingerprint = aggregate_sha256(
        [
            {
                "provider": provider,
                "source_path": resolved_source_path,
                "connector_kind": connector_kind,
                "connector_version": connector_version,
                "connector_ref_sha256": _sha256_text(connector_ref),
                "connector_binary_ref_sha256": _sha256_text(connector_binary_ref)
                if connector_binary_ref
                else None,
                "supported_capabilities": capability_review["supported_capabilities"],
                "transport_mode": "connector_reference_only",
            }
        ]
    )
    return {
        "artifact_kind": "scout_wearable_provider_live_connector_reference",
        "artifact_version": "wearable_provider_live_connector_reference.v1",
        "source_provider": provider,
        "source_path": resolved_source_path,
        "sha256": source_fingerprint,
        "connector": {
            "provider": provider,
            "connector_kind": connector_kind,
            "connector_version": connector_version,
            "connector_ref_present": True,
            "connector_ref_sha256": _sha256_text(connector_ref),
            "connector_ref_exposed": False,
            "connector_binary_ref_present": connector_binary_ref is not None
            and bool(connector_binary_ref.strip()),
            "connector_binary_ref_sha256": _sha256_text(connector_binary_ref)
            if connector_binary_ref
            else None,
            "connector_binary_ref_exposed": False,
            "connector_process_started": False,
            "connector_health_check_performed": False,
            "connector_live_request_performed": False,
            "connector_execution_bound": False,
            "credential_values_loaded": False,
            "credential_values_exposed": False,
            "supported_capabilities": capability_review["supported_capabilities"],
        },
        "authorization": {
            "provider": provider,
            "explicit_consent": True,
            "connector_reference_authorized": True,
            "supported_capabilities": capability_review["supported_capabilities"],
        },
        "capability_review": capability_review,
        "transport": {
            "transport_mode": "connector_reference_only",
            "connector_reference_only": True,
            "request_executor_bound": False,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "raw_response_committed": False,
        },
        "data_quality": data_quality.model_dump(mode="json"),
        "privacy": privacy.model_dump(mode="json"),
        "boundary": boundary.model_dump(mode="json"),
        "mutation": {
            "source_file_mutated": False,
            "connector_process_started": False,
            "connector_health_check_performed": False,
            "connector_live_request_performed": False,
            "connector_execution_bound": False,
            "credential_values_loaded": False,
            "credential_values_exposed": False,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "phase1_runtime_mutated": False,
            "safety_api_called": False,
            "raw_payload_committed": False,
            "raw_health_payload_shared": False,
            "raw_track_shared": False,
            "exact_timestamps_shared": False,
        },
    }


def write_provider_live_connector_reference(
    *,
    provider: ProviderLiveTransportProvider,
    output_path: Path,
    explicit_consent: bool,
    connector_kind: ProviderLiveConnectorKind,
    connector_ref: str,
    connector_version: str,
    supported_capabilities: list[str],
    connector_binary_ref: str | None = None,
    source_path: str | None = None,
) -> dict[str, Any]:
    artifact = build_provider_live_connector_reference(
        provider=provider,
        explicit_consent=explicit_consent,
        connector_kind=connector_kind,
        connector_ref=connector_ref,
        connector_version=connector_version,
        connector_binary_ref=connector_binary_ref,
        supported_capabilities=supported_capabilities,
        source_path=source_path,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "artifact_kind": "scout_wearable_provider_live_connector_reference_result",
        "artifact_version": "wearable_provider_live_connector_reference_result.v1",
        "source_provider": artifact["source_provider"],
        "source_path": artifact["source_path"],
        "sha256": artifact["sha256"],
        "connector_reference_path": str(output_path),
        "connector_reference": artifact,
        "data_quality": artifact["data_quality"],
        "privacy": artifact["privacy"],
        "boundary": artifact["boundary"],
        "mutation": {
            "connector_reference_artifact_written": True,
            "source_file_mutated": False,
            "connector_process_started": False,
            "connector_health_check_performed": False,
            "connector_live_request_performed": False,
            "connector_execution_bound": False,
            "credential_values_loaded": False,
            "credential_values_exposed": False,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "phase1_runtime_mutated": False,
            "safety_api_called": False,
            "raw_payload_committed": False,
            "raw_health_payload_shared": False,
            "raw_track_shared": False,
            "exact_timestamps_shared": False,
        },
    }


def load_provider_live_connector_reference(
    connector_reference_path: Path,
) -> dict[str, Any]:
    payload = json.loads(connector_reference_path.read_text(encoding="utf-8"))
    if payload.get("artifact_kind") != "scout_wearable_provider_live_connector_reference":
        raise ValueError("provider live connector reference artifact is required")
    return payload


def assert_provider_live_connector_reference_safe(
    connector_reference: dict[str, Any],
) -> None:
    connector = connector_reference.get("connector", {})
    if (
        not connector.get("connector_ref_sha256")
        or connector.get("connector_ref_exposed")
        or connector.get("connector_binary_ref_exposed")
        or connector.get("connector_process_started")
        or connector.get("connector_health_check_performed")
        or connector.get("connector_live_request_performed")
        or connector.get("connector_execution_bound")
        or connector.get("credential_values_loaded")
        or connector.get("credential_values_exposed")
    ):
        raise ValueError("connector reference must contain local digest refs only")
    authorization = connector_reference.get("authorization", {})
    if not authorization.get("explicit_consent"):
        raise ValueError("connector reference requires explicit consent")
    if not connector_reference.get("capability_review", {}).get("capability_flags_valid"):
        raise ValueError("connector reference requires valid capability flags")
    transport = connector_reference.get("transport", {})
    if (
        transport.get("transport_mode") != "connector_reference_only"
        or transport.get("request_executor_bound")
        or transport.get("network_request_performed")
        or transport.get("network_sync_performed")
        or transport.get("remote_upload_allowed")
        or transport.get("remote_upload_performed")
        or transport.get("real_provider_api_called")
        or transport.get("runtime_ingest_performed")
    ):
        raise ValueError("connector reference requires local-only transport")
    privacy = connector_reference.get("privacy", {})
    if privacy.get("raw_health_payload_shared") or privacy.get("raw_track_shared") or privacy.get("exact_timestamps_shared"):
        raise ValueError("connector reference requires sanitized privacy")
    boundary = connector_reference.get("boundary", {})
    if boundary.get("medical_diagnosis") or boundary.get("phase1_runtime_safety_truth"):
        raise ValueError("connector reference cannot use medical or Phase 1 safety truth")


def build_provider_live_network_policy_reference(
    *,
    provider: ProviderLiveTransportProvider,
    explicit_consent: bool,
    policy_ref: str,
    endpoint_ref: str,
    allowed_capabilities: list[str],
    egress_profile_ref: str | None = None,
    tls_profile_ref: str | None = None,
    source_path: str | None = None,
    dns_lookup_performed: bool = False,
    network_socket_opened: bool = False,
    tls_handshake_performed: bool = False,
    http_request_performed: bool = False,
    network_request_performed: bool = False,
    real_provider_api_called: bool = False,
    remote_upload_performed: bool = False,
    runtime_ingest_performed: bool = False,
) -> dict[str, Any]:
    if provider not in _PROVIDER_SUPPORTED_CAPABILITIES:
        raise ValueError(f"provider network policy reference is not supported: {provider}")
    if not explicit_consent:
        raise ValueError("explicit consent is required before provider network policy reference")
    if not policy_ref.strip():
        raise ValueError("network policy ref is required before provider network policy reference")
    if not endpoint_ref.strip():
        raise ValueError("endpoint ref is required before provider network policy reference")
    if not allowed_capabilities:
        raise ValueError("at least one capability flag is required before provider network policy reference")
    _assert_network_policy_reference_only(
        dns_lookup_performed=dns_lookup_performed,
        network_socket_opened=network_socket_opened,
        tls_handshake_performed=tls_handshake_performed,
        http_request_performed=http_request_performed,
        network_request_performed=network_request_performed,
        real_provider_api_called=real_provider_api_called,
        remote_upload_performed=remote_upload_performed,
        runtime_ingest_performed=runtime_ingest_performed,
    )

    capability_review = _review_connector_capabilities(
        provider,
        supported_capabilities=allowed_capabilities,
    )
    if not capability_review["capability_flags_valid"]:
        raise ValueError("provider network policy reference requires supported capabilities")
    resolved_source_path = source_path or f"provider-live-network-policy-reference://{provider}"
    data_quality = ScoutEnergyDataQuality(
        heart_rate_confidence="low",
        gps_confidence="low",
        provider_value_confidence="low",
        limitations=[
            "provider network policy reference records endpoint and policy refs as sha256 digests only",
            "no DNS lookup, socket open, TLS handshake, HTTP request, or provider API call is performed",
            "network policy reference is not a runtime-ingest or safety-truth authorization",
        ],
    )
    privacy = ScoutEnergyPrivacy()
    boundary = ScoutEnergyBoundary()
    source_fingerprint = aggregate_sha256(
        [
            {
                "provider": provider,
                "source_path": resolved_source_path,
                "policy_ref_sha256": _sha256_text(policy_ref),
                "endpoint_ref_sha256": _sha256_text(endpoint_ref),
                "egress_profile_ref_sha256": _sha256_text(egress_profile_ref)
                if egress_profile_ref
                else None,
                "tls_profile_ref_sha256": _sha256_text(tls_profile_ref)
                if tls_profile_ref
                else None,
                "allowed_capabilities": capability_review["supported_capabilities"],
                "transport_mode": "network_policy_reference_only",
            }
        ]
    )
    return {
        "artifact_kind": "scout_wearable_provider_live_network_policy_reference",
        "artifact_version": "wearable_provider_live_network_policy_reference.v1",
        "source_provider": provider,
        "source_path": resolved_source_path,
        "sha256": source_fingerprint,
        "network_policy": {
            "provider": provider,
            "policy_ref_present": True,
            "policy_ref_sha256": _sha256_text(policy_ref),
            "policy_ref_exposed": False,
            "endpoint_ref_present": True,
            "endpoint_ref_sha256": _sha256_text(endpoint_ref),
            "endpoint_ref_exposed": False,
            "egress_profile_ref_present": egress_profile_ref is not None
            and bool(egress_profile_ref.strip()),
            "egress_profile_ref_sha256": _sha256_text(egress_profile_ref)
            if egress_profile_ref
            else None,
            "egress_profile_ref_exposed": False,
            "tls_profile_ref_present": tls_profile_ref is not None
            and bool(tls_profile_ref.strip()),
            "tls_profile_ref_sha256": _sha256_text(tls_profile_ref)
            if tls_profile_ref
            else None,
            "tls_profile_ref_exposed": False,
            "dns_lookup_performed": False,
            "network_socket_opened": False,
            "tls_handshake_performed": False,
            "http_request_performed": False,
            "network_request_performed": False,
            "real_provider_api_called": False,
            "remote_upload_performed": False,
            "runtime_ingest_performed": False,
            "allowed_capabilities": capability_review["supported_capabilities"],
        },
        "authorization": {
            "provider": provider,
            "explicit_consent": True,
            "network_policy_reference_recorded": True,
            "allowed_capabilities": capability_review["supported_capabilities"],
        },
        "capability_review": capability_review,
        "transport": {
            "transport_mode": "network_policy_reference_only",
            "network_policy_reference_only": True,
            "request_executor_bound": False,
            "dns_lookup_performed": False,
            "network_socket_opened": False,
            "tls_handshake_performed": False,
            "http_request_performed": False,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "raw_response_committed": False,
        },
        "data_quality": data_quality.model_dump(mode="json"),
        "privacy": privacy.model_dump(mode="json"),
        "boundary": boundary.model_dump(mode="json"),
        "mutation": {
            "source_file_mutated": False,
            "dns_lookup_performed": False,
            "network_socket_opened": False,
            "tls_handshake_performed": False,
            "http_request_performed": False,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "phase1_runtime_mutated": False,
            "safety_api_called": False,
            "raw_payload_committed": False,
            "raw_health_payload_shared": False,
            "raw_track_shared": False,
            "exact_timestamps_shared": False,
        },
    }


def write_provider_live_network_policy_reference(
    *,
    provider: ProviderLiveTransportProvider,
    output_path: Path,
    explicit_consent: bool,
    policy_ref: str,
    endpoint_ref: str,
    allowed_capabilities: list[str],
    egress_profile_ref: str | None = None,
    tls_profile_ref: str | None = None,
    source_path: str | None = None,
) -> dict[str, Any]:
    artifact = build_provider_live_network_policy_reference(
        provider=provider,
        explicit_consent=explicit_consent,
        policy_ref=policy_ref,
        endpoint_ref=endpoint_ref,
        egress_profile_ref=egress_profile_ref,
        tls_profile_ref=tls_profile_ref,
        allowed_capabilities=allowed_capabilities,
        source_path=source_path,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "artifact_kind": "scout_wearable_provider_live_network_policy_reference_result",
        "artifact_version": "wearable_provider_live_network_policy_reference_result.v1",
        "source_provider": artifact["source_provider"],
        "source_path": artifact["source_path"],
        "sha256": artifact["sha256"],
        "network_policy_reference_path": str(output_path),
        "network_policy_reference": artifact,
        "data_quality": artifact["data_quality"],
        "privacy": artifact["privacy"],
        "boundary": artifact["boundary"],
        "mutation": {
            "network_policy_reference_artifact_written": True,
            "source_file_mutated": False,
            "dns_lookup_performed": False,
            "network_socket_opened": False,
            "tls_handshake_performed": False,
            "http_request_performed": False,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "phase1_runtime_mutated": False,
            "safety_api_called": False,
            "raw_payload_committed": False,
            "raw_health_payload_shared": False,
            "raw_track_shared": False,
            "exact_timestamps_shared": False,
        },
    }


def load_provider_live_network_policy_reference(
    network_policy_reference_path: Path,
) -> dict[str, Any]:
    payload = json.loads(network_policy_reference_path.read_text(encoding="utf-8"))
    if payload.get("artifact_kind") != "scout_wearable_provider_live_network_policy_reference":
        raise ValueError("provider live network policy reference artifact is required")
    return payload


def assert_provider_live_network_policy_reference_safe(
    network_policy_reference: dict[str, Any],
) -> None:
    network_policy = network_policy_reference.get("network_policy", {})
    if (
        not network_policy.get("policy_ref_sha256")
        or not network_policy.get("endpoint_ref_sha256")
        or network_policy.get("policy_ref_exposed")
        or network_policy.get("endpoint_ref_exposed")
        or network_policy.get("egress_profile_ref_exposed")
        or network_policy.get("tls_profile_ref_exposed")
        or network_policy.get("dns_lookup_performed")
        or network_policy.get("network_socket_opened")
        or network_policy.get("tls_handshake_performed")
        or network_policy.get("http_request_performed")
        or network_policy.get("network_request_performed")
        or network_policy.get("real_provider_api_called")
        or network_policy.get("remote_upload_performed")
        or network_policy.get("runtime_ingest_performed")
    ):
        raise ValueError("network policy reference must contain local digest refs only")
    authorization = network_policy_reference.get("authorization", {})
    if not authorization.get("explicit_consent"):
        raise ValueError("network policy reference requires explicit consent")
    if not network_policy_reference.get("capability_review", {}).get("capability_flags_valid"):
        raise ValueError("network policy reference requires valid capability flags")
    transport = network_policy_reference.get("transport", {})
    if (
        transport.get("transport_mode") != "network_policy_reference_only"
        or transport.get("request_executor_bound")
        or transport.get("dns_lookup_performed")
        or transport.get("network_socket_opened")
        or transport.get("tls_handshake_performed")
        or transport.get("http_request_performed")
        or transport.get("network_request_performed")
        or transport.get("network_sync_performed")
        or transport.get("remote_upload_allowed")
        or transport.get("remote_upload_performed")
        or transport.get("real_provider_api_called")
        or transport.get("runtime_ingest_performed")
    ):
        raise ValueError("network policy reference requires local-only transport")
    privacy = network_policy_reference.get("privacy", {})
    if privacy.get("raw_health_payload_shared") or privacy.get("raw_track_shared") or privacy.get("exact_timestamps_shared"):
        raise ValueError("network policy reference requires sanitized privacy")
    boundary = network_policy_reference.get("boundary", {})
    if boundary.get("medical_diagnosis") or boundary.get("phase1_runtime_safety_truth"):
        raise ValueError("network policy reference cannot use medical or Phase 1 safety truth")


def build_provider_live_runtime_ingest_boundary_reference(
    *,
    provider: ProviderLiveTransportProvider,
    explicit_consent: bool,
    runtime_boundary_ref: str,
    runtime_channel_ref: str,
    allowed_artifact_kinds: list[str],
    handoff_mode: str = "post_analysis_reference_only",
    source_path: str | None = None,
    runtime_ingest_performed: bool = False,
    runtime_write_performed: bool = False,
    phase1_runtime_mutated: bool = False,
    phase1_runtime_safety_truth: bool = False,
    safety_api_called: bool = False,
    network_request_performed: bool = False,
    real_provider_api_called: bool = False,
) -> dict[str, Any]:
    if provider not in _PROVIDER_SUPPORTED_CAPABILITIES:
        raise ValueError(f"provider runtime ingest boundary reference is not supported: {provider}")
    if not explicit_consent:
        raise ValueError("explicit consent is required before runtime ingest boundary reference")
    if not runtime_boundary_ref.strip():
        raise ValueError("runtime boundary ref is required before runtime ingest boundary reference")
    if not runtime_channel_ref.strip():
        raise ValueError("runtime channel ref is required before runtime ingest boundary reference")
    if not allowed_artifact_kinds:
        raise ValueError("at least one artifact kind is required before runtime ingest boundary reference")
    if handoff_mode not in {
        "post_analysis_reference_only",
        "advisory_energy_reference_only",
    }:
        raise ValueError("runtime ingest boundary reference handoff mode is not supported")
    _assert_runtime_ingest_boundary_reference_only(
        runtime_ingest_performed=runtime_ingest_performed,
        runtime_write_performed=runtime_write_performed,
        phase1_runtime_mutated=phase1_runtime_mutated,
        phase1_runtime_safety_truth=phase1_runtime_safety_truth,
        safety_api_called=safety_api_called,
        network_request_performed=network_request_performed,
        real_provider_api_called=real_provider_api_called,
    )

    artifact_kinds = _dedupe([kind.strip() for kind in allowed_artifact_kinds if kind.strip()])
    if not artifact_kinds:
        raise ValueError("runtime ingest boundary reference requires artifact kinds")
    resolved_source_path = source_path or f"provider-live-runtime-ingest-boundary-reference://{provider}"
    data_quality = ScoutEnergyDataQuality(
        heart_rate_confidence="low",
        gps_confidence="low",
        provider_value_confidence="low",
        limitations=[
            "runtime ingest boundary reference records runtime refs as sha256 digests only",
            "runtime ingest, runtime writes, Phase 1 safety truth, and safety API calls remain disabled",
            "this artifact is an advisory post-analysis handoff boundary record, not runtime truth",
        ],
    )
    privacy = ScoutEnergyPrivacy()
    boundary = ScoutEnergyBoundary()
    source_fingerprint = aggregate_sha256(
        [
            {
                "provider": provider,
                "source_path": resolved_source_path,
                "runtime_boundary_ref_sha256": _sha256_text(runtime_boundary_ref),
                "runtime_channel_ref_sha256": _sha256_text(runtime_channel_ref),
                "allowed_artifact_kinds": artifact_kinds,
                "handoff_mode": handoff_mode,
                "transport_mode": "runtime_ingest_boundary_reference_only",
            }
        ]
    )
    return {
        "artifact_kind": "scout_wearable_provider_live_runtime_ingest_boundary_reference",
        "artifact_version": "wearable_provider_live_runtime_ingest_boundary_reference.v1",
        "source_provider": provider,
        "source_path": resolved_source_path,
        "sha256": source_fingerprint,
        "runtime_ingest_boundary": {
            "provider": provider,
            "handoff_mode": handoff_mode,
            "runtime_boundary_ref_present": True,
            "runtime_boundary_ref_sha256": _sha256_text(runtime_boundary_ref),
            "runtime_boundary_ref_exposed": False,
            "runtime_channel_ref_present": True,
            "runtime_channel_ref_sha256": _sha256_text(runtime_channel_ref),
            "runtime_channel_ref_exposed": False,
            "allowed_artifact_kinds": artifact_kinds,
            "post_analysis_reference_only": True,
            "advisory_only": True,
            "runtime_ingest_authorized": False,
            "runtime_ingest_performed": False,
            "runtime_write_performed": False,
            "phase1_runtime_mutated": False,
            "phase1_runtime_safety_truth": False,
            "phase1_safety_state_mutation_allowed": False,
            "safety_api_called": False,
            "medical_diagnosis": False,
        },
        "authorization": {
            "provider": provider,
            "explicit_consent": True,
            "runtime_ingest_authorized": False,
            "allowed_artifact_kinds": artifact_kinds,
        },
        "transport": {
            "transport_mode": "runtime_ingest_boundary_reference_only",
            "runtime_ingest_boundary_reference_only": True,
            "request_executor_bound": False,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "runtime_write_performed": False,
            "phase1_runtime_mutated": False,
            "safety_api_called": False,
            "raw_response_committed": False,
        },
        "data_quality": data_quality.model_dump(mode="json"),
        "privacy": privacy.model_dump(mode="json"),
        "boundary": boundary.model_dump(mode="json"),
        "mutation": {
            "source_file_mutated": False,
            "runtime_ingest_performed": False,
            "runtime_write_performed": False,
            "phase1_runtime_mutated": False,
            "phase1_runtime_safety_truth": False,
            "phase1_safety_state_mutation_allowed": False,
            "safety_api_called": False,
            "medical_diagnosis": False,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "raw_payload_committed": False,
            "raw_health_payload_shared": False,
            "raw_track_shared": False,
            "exact_timestamps_shared": False,
        },
    }


def write_provider_live_runtime_ingest_boundary_reference(
    *,
    provider: ProviderLiveTransportProvider,
    output_path: Path,
    explicit_consent: bool,
    runtime_boundary_ref: str,
    runtime_channel_ref: str,
    allowed_artifact_kinds: list[str],
    handoff_mode: str = "post_analysis_reference_only",
    source_path: str | None = None,
) -> dict[str, Any]:
    artifact = build_provider_live_runtime_ingest_boundary_reference(
        provider=provider,
        explicit_consent=explicit_consent,
        runtime_boundary_ref=runtime_boundary_ref,
        runtime_channel_ref=runtime_channel_ref,
        allowed_artifact_kinds=allowed_artifact_kinds,
        handoff_mode=handoff_mode,
        source_path=source_path,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "artifact_kind": "scout_wearable_provider_live_runtime_ingest_boundary_reference_result",
        "artifact_version": "wearable_provider_live_runtime_ingest_boundary_reference_result.v1",
        "source_provider": artifact["source_provider"],
        "source_path": artifact["source_path"],
        "sha256": artifact["sha256"],
        "runtime_ingest_boundary_reference_path": str(output_path),
        "runtime_ingest_boundary_reference": artifact,
        "data_quality": artifact["data_quality"],
        "privacy": artifact["privacy"],
        "boundary": artifact["boundary"],
        "mutation": {
            "runtime_ingest_boundary_reference_artifact_written": True,
            "source_file_mutated": False,
            "runtime_ingest_performed": False,
            "runtime_write_performed": False,
            "phase1_runtime_mutated": False,
            "phase1_runtime_safety_truth": False,
            "phase1_safety_state_mutation_allowed": False,
            "safety_api_called": False,
            "medical_diagnosis": False,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "raw_payload_committed": False,
            "raw_health_payload_shared": False,
            "raw_track_shared": False,
            "exact_timestamps_shared": False,
        },
    }


def load_provider_live_runtime_ingest_boundary_reference(
    runtime_ingest_boundary_reference_path: Path,
) -> dict[str, Any]:
    payload = json.loads(runtime_ingest_boundary_reference_path.read_text(encoding="utf-8"))
    if payload.get("artifact_kind") != "scout_wearable_provider_live_runtime_ingest_boundary_reference":
        raise ValueError("provider live runtime ingest boundary reference artifact is required")
    return payload


def assert_provider_live_runtime_ingest_boundary_reference_safe(
    runtime_ingest_boundary_reference: dict[str, Any],
) -> None:
    runtime_boundary = runtime_ingest_boundary_reference.get("runtime_ingest_boundary", {})
    if (
        not runtime_boundary.get("runtime_boundary_ref_sha256")
        or not runtime_boundary.get("runtime_channel_ref_sha256")
        or runtime_boundary.get("runtime_boundary_ref_exposed")
        or runtime_boundary.get("runtime_channel_ref_exposed")
        or runtime_boundary.get("runtime_ingest_authorized")
        or runtime_boundary.get("runtime_ingest_performed")
        or runtime_boundary.get("runtime_write_performed")
        or runtime_boundary.get("phase1_runtime_mutated")
        or runtime_boundary.get("phase1_runtime_safety_truth")
        or runtime_boundary.get("phase1_safety_state_mutation_allowed")
        or runtime_boundary.get("safety_api_called")
        or runtime_boundary.get("medical_diagnosis")
    ):
        raise ValueError("runtime ingest boundary reference must remain advisory only")
    authorization = runtime_ingest_boundary_reference.get("authorization", {})
    if not authorization.get("explicit_consent") or authorization.get("runtime_ingest_authorized"):
        raise ValueError("runtime ingest boundary reference requires consent without runtime authorization")
    transport = runtime_ingest_boundary_reference.get("transport", {})
    if (
        transport.get("transport_mode") != "runtime_ingest_boundary_reference_only"
        or transport.get("request_executor_bound")
        or transport.get("network_request_performed")
        or transport.get("network_sync_performed")
        or transport.get("remote_upload_allowed")
        or transport.get("remote_upload_performed")
        or transport.get("real_provider_api_called")
        or transport.get("runtime_ingest_performed")
        or transport.get("runtime_write_performed")
        or transport.get("phase1_runtime_mutated")
        or transport.get("safety_api_called")
    ):
        raise ValueError("runtime ingest boundary reference requires local-only transport")
    privacy = runtime_ingest_boundary_reference.get("privacy", {})
    if privacy.get("raw_health_payload_shared") or privacy.get("raw_track_shared") or privacy.get("exact_timestamps_shared"):
        raise ValueError("runtime ingest boundary reference requires sanitized privacy")
    boundary = runtime_ingest_boundary_reference.get("boundary", {})
    if boundary.get("medical_diagnosis") or boundary.get("phase1_runtime_safety_truth"):
        raise ValueError("runtime ingest boundary reference cannot use medical or Phase 1 safety truth")


def build_provider_live_phase1_safety_boundary_reference(
    *,
    provider: ProviderLiveTransportProvider,
    explicit_consent: bool,
    phase1_boundary_ref: str,
    phase1_state_ref: str,
    advisory_channel_ref: str,
    allowed_artifact_kinds: list[str],
    handoff_mode: str = "advisory_reference_only",
    source_path: str | None = None,
    phase1_runtime_mutated: bool = False,
    phase1_runtime_safety_truth: bool = False,
    phase1_l0_l4_state_mutated: bool = False,
    phase1_safety_state_mutation_allowed: bool = False,
    safety_api_called: bool = False,
    medical_diagnosis: bool = False,
    runtime_ingest_performed: bool = False,
    runtime_write_performed: bool = False,
    network_request_performed: bool = False,
    real_provider_api_called: bool = False,
    provider_values_are_scout_truth: bool = False,
) -> dict[str, Any]:
    if provider not in _PROVIDER_SUPPORTED_CAPABILITIES:
        raise ValueError(f"provider Phase 1 safety boundary reference is not supported: {provider}")
    if not explicit_consent:
        raise ValueError("explicit consent is required before Phase 1 safety boundary reference")
    if not phase1_boundary_ref.strip():
        raise ValueError("Phase 1 boundary ref is required before Phase 1 safety boundary reference")
    if not phase1_state_ref.strip():
        raise ValueError("Phase 1 state ref is required before Phase 1 safety boundary reference")
    if not advisory_channel_ref.strip():
        raise ValueError("advisory channel ref is required before Phase 1 safety boundary reference")
    if not allowed_artifact_kinds:
        raise ValueError("at least one artifact kind is required before Phase 1 safety boundary reference")
    if handoff_mode not in {
        "advisory_reference_only",
        "post_analysis_reference_only",
        "advisory_energy_reference_only",
    }:
        raise ValueError("Phase 1 safety boundary reference handoff mode is not supported")
    _assert_phase1_safety_boundary_reference_only(
        phase1_runtime_mutated=phase1_runtime_mutated,
        phase1_runtime_safety_truth=phase1_runtime_safety_truth,
        phase1_l0_l4_state_mutated=phase1_l0_l4_state_mutated,
        phase1_safety_state_mutation_allowed=phase1_safety_state_mutation_allowed,
        safety_api_called=safety_api_called,
        medical_diagnosis=medical_diagnosis,
        runtime_ingest_performed=runtime_ingest_performed,
        runtime_write_performed=runtime_write_performed,
        network_request_performed=network_request_performed,
        real_provider_api_called=real_provider_api_called,
        provider_values_are_scout_truth=provider_values_are_scout_truth,
    )

    artifact_kinds = _dedupe([kind.strip() for kind in allowed_artifact_kinds if kind.strip()])
    if not artifact_kinds:
        raise ValueError("Phase 1 safety boundary reference requires artifact kinds")
    resolved_source_path = source_path or f"provider-live-phase1-safety-boundary-reference://{provider}"
    data_quality = ScoutEnergyDataQuality(
        heart_rate_confidence="low",
        gps_confidence="low",
        provider_value_confidence="low",
        limitations=[
            "Phase 1 boundary, state, and advisory channel refs are recorded as sha256 digests only",
            "wearable energy artifacts remain advisory references and are not Phase 1 runtime safety truth",
            "Phase 1 L0-L4 safety state mutation, safety API calls, runtime ingest, and medical diagnosis remain disabled",
        ],
    )
    privacy = ScoutEnergyPrivacy()
    boundary = ScoutEnergyBoundary()
    source_fingerprint = aggregate_sha256(
        [
            {
                "provider": provider,
                "source_path": resolved_source_path,
                "phase1_boundary_ref_sha256": _sha256_text(phase1_boundary_ref),
                "phase1_state_ref_sha256": _sha256_text(phase1_state_ref),
                "advisory_channel_ref_sha256": _sha256_text(advisory_channel_ref),
                "allowed_artifact_kinds": artifact_kinds,
                "handoff_mode": handoff_mode,
                "transport_mode": "phase1_safety_boundary_reference_only",
            }
        ]
    )
    return {
        "artifact_kind": "scout_wearable_provider_live_phase1_safety_boundary_reference",
        "artifact_version": "wearable_provider_live_phase1_safety_boundary_reference.v1",
        "source_provider": provider,
        "source_path": resolved_source_path,
        "sha256": source_fingerprint,
        "phase1_safety_boundary": {
            "provider": provider,
            "handoff_mode": handoff_mode,
            "phase1_boundary_ref_present": True,
            "phase1_boundary_ref_sha256": _sha256_text(phase1_boundary_ref),
            "phase1_boundary_ref_exposed": False,
            "phase1_state_ref_present": True,
            "phase1_state_ref_sha256": _sha256_text(phase1_state_ref),
            "phase1_state_ref_exposed": False,
            "advisory_channel_ref_present": True,
            "advisory_channel_ref_sha256": _sha256_text(advisory_channel_ref),
            "advisory_channel_ref_exposed": False,
            "allowed_artifact_kinds": artifact_kinds,
            "advisory_only": True,
            "not_safety_truth": True,
            "phase1_runtime_safety_truth": False,
            "phase1_runtime_mutated": False,
            "phase1_l0_l4_state_mutated": False,
            "phase1_safety_state_mutation_allowed": False,
            "safety_api_called": False,
            "medical_diagnosis": False,
            "runtime_ingest_performed": False,
            "runtime_write_performed": False,
            "provider_values_are_scout_truth": False,
        },
        "authorization": {
            "provider": provider,
            "explicit_consent": True,
            "phase1_safety_truth_authorized": False,
            "phase1_state_mutation_authorized": False,
            "allowed_artifact_kinds": artifact_kinds,
        },
        "transport": {
            "transport_mode": "phase1_safety_boundary_reference_only",
            "phase1_safety_boundary_reference_only": True,
            "request_executor_bound": False,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "runtime_write_performed": False,
            "phase1_runtime_mutated": False,
            "phase1_l0_l4_state_mutated": False,
            "safety_api_called": False,
            "raw_response_committed": False,
        },
        "data_quality": data_quality.model_dump(mode="json"),
        "privacy": privacy.model_dump(mode="json"),
        "boundary": boundary.model_dump(mode="json"),
        "mutation": {
            "source_file_mutated": False,
            "runtime_ingest_performed": False,
            "runtime_write_performed": False,
            "phase1_runtime_mutated": False,
            "phase1_runtime_safety_truth": False,
            "phase1_l0_l4_state_mutated": False,
            "phase1_safety_state_mutation_allowed": False,
            "safety_api_called": False,
            "medical_diagnosis": False,
            "provider_values_are_scout_truth": False,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "raw_payload_committed": False,
            "raw_health_payload_shared": False,
            "raw_track_shared": False,
            "exact_timestamps_shared": False,
        },
    }


def write_provider_live_phase1_safety_boundary_reference(
    *,
    provider: ProviderLiveTransportProvider,
    output_path: Path,
    explicit_consent: bool,
    phase1_boundary_ref: str,
    phase1_state_ref: str,
    advisory_channel_ref: str,
    allowed_artifact_kinds: list[str],
    handoff_mode: str = "advisory_reference_only",
    source_path: str | None = None,
) -> dict[str, Any]:
    artifact = build_provider_live_phase1_safety_boundary_reference(
        provider=provider,
        explicit_consent=explicit_consent,
        phase1_boundary_ref=phase1_boundary_ref,
        phase1_state_ref=phase1_state_ref,
        advisory_channel_ref=advisory_channel_ref,
        allowed_artifact_kinds=allowed_artifact_kinds,
        handoff_mode=handoff_mode,
        source_path=source_path,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "artifact_kind": "scout_wearable_provider_live_phase1_safety_boundary_reference_result",
        "artifact_version": "wearable_provider_live_phase1_safety_boundary_reference_result.v1",
        "source_provider": artifact["source_provider"],
        "source_path": artifact["source_path"],
        "sha256": artifact["sha256"],
        "phase1_safety_boundary_reference_path": str(output_path),
        "phase1_safety_boundary_reference": artifact,
        "data_quality": artifact["data_quality"],
        "privacy": artifact["privacy"],
        "boundary": artifact["boundary"],
        "mutation": {
            "phase1_safety_boundary_reference_artifact_written": True,
            "source_file_mutated": False,
            "runtime_ingest_performed": False,
            "runtime_write_performed": False,
            "phase1_runtime_mutated": False,
            "phase1_runtime_safety_truth": False,
            "phase1_l0_l4_state_mutated": False,
            "phase1_safety_state_mutation_allowed": False,
            "safety_api_called": False,
            "medical_diagnosis": False,
            "provider_values_are_scout_truth": False,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "raw_payload_committed": False,
            "raw_health_payload_shared": False,
            "raw_track_shared": False,
            "exact_timestamps_shared": False,
        },
    }


def load_provider_live_phase1_safety_boundary_reference(
    phase1_safety_boundary_reference_path: Path,
) -> dict[str, Any]:
    payload = json.loads(phase1_safety_boundary_reference_path.read_text(encoding="utf-8"))
    if payload.get("artifact_kind") != "scout_wearable_provider_live_phase1_safety_boundary_reference":
        raise ValueError("provider live Phase 1 safety boundary reference artifact is required")
    return payload


def assert_provider_live_phase1_safety_boundary_reference_safe(
    phase1_safety_boundary_reference: dict[str, Any],
) -> None:
    phase1_boundary = phase1_safety_boundary_reference.get("phase1_safety_boundary", {})
    if (
        not phase1_boundary.get("phase1_boundary_ref_sha256")
        or not phase1_boundary.get("phase1_state_ref_sha256")
        or not phase1_boundary.get("advisory_channel_ref_sha256")
        or phase1_boundary.get("phase1_boundary_ref_exposed")
        or phase1_boundary.get("phase1_state_ref_exposed")
        or phase1_boundary.get("advisory_channel_ref_exposed")
        or not phase1_boundary.get("advisory_only")
        or not phase1_boundary.get("not_safety_truth")
        or phase1_boundary.get("phase1_runtime_safety_truth")
        or phase1_boundary.get("phase1_runtime_mutated")
        or phase1_boundary.get("phase1_l0_l4_state_mutated")
        or phase1_boundary.get("phase1_safety_state_mutation_allowed")
        or phase1_boundary.get("safety_api_called")
        or phase1_boundary.get("medical_diagnosis")
        or phase1_boundary.get("runtime_ingest_performed")
        or phase1_boundary.get("runtime_write_performed")
        or phase1_boundary.get("provider_values_are_scout_truth")
    ):
        raise ValueError("Phase 1 safety boundary reference must remain advisory only")
    authorization = phase1_safety_boundary_reference.get("authorization", {})
    if (
        not authorization.get("explicit_consent")
        or authorization.get("phase1_safety_truth_authorized")
        or authorization.get("phase1_state_mutation_authorized")
    ):
        raise ValueError("Phase 1 safety boundary reference requires consent without Phase 1 mutation authorization")
    transport = phase1_safety_boundary_reference.get("transport", {})
    if (
        transport.get("transport_mode") != "phase1_safety_boundary_reference_only"
        or transport.get("request_executor_bound")
        or transport.get("network_request_performed")
        or transport.get("network_sync_performed")
        or transport.get("remote_upload_allowed")
        or transport.get("remote_upload_performed")
        or transport.get("real_provider_api_called")
        or transport.get("runtime_ingest_performed")
        or transport.get("runtime_write_performed")
        or transport.get("phase1_runtime_mutated")
        or transport.get("phase1_l0_l4_state_mutated")
        or transport.get("safety_api_called")
    ):
        raise ValueError("Phase 1 safety boundary reference requires local-only transport")
    privacy = phase1_safety_boundary_reference.get("privacy", {})
    if privacy.get("raw_health_payload_shared") or privacy.get("raw_track_shared") or privacy.get("exact_timestamps_shared"):
        raise ValueError("Phase 1 safety boundary reference requires sanitized privacy")
    boundary = phase1_safety_boundary_reference.get("boundary", {})
    if (
        boundary.get("medical_diagnosis")
        or boundary.get("phase1_runtime_safety_truth")
        or boundary.get("phase1_safety_state_mutation_allowed")
        or boundary.get("provider_values_are_scout_truth")
    ):
        raise ValueError("Phase 1 safety boundary reference cannot use medical or Phase 1 safety truth")


def build_provider_live_transport_request_plan(
    *,
    preflight_path: Path,
    window_start_date: str,
    window_end_date: str,
    requested_capabilities: list[str] | None = None,
) -> dict[str, Any]:
    preflight = _load_preflight_artifact(preflight_path)
    _assert_preflight_artifact_safe(preflight)
    query_window = _query_window(window_start_date, window_end_date)
    allowed_capabilities = preflight["capability_review"]["allowed_capabilities"]
    selected_capabilities = requested_capabilities or allowed_capabilities
    _assert_capabilities_allowed(selected_capabilities, allowed_capabilities)
    provider = preflight["source_provider"]
    request_slots = [
        _request_slot(
            provider=provider,
            capability=capability,
            preflight_sha=preflight["sha256"],
            normalized_scopes=preflight["authorization"]["normalized_scopes"],
            query_window=query_window,
        )
        for capability in selected_capabilities
    ]
    data_quality = ScoutEnergyDataQuality(
        heart_rate_confidence="low",
        gps_confidence="low",
        provider_value_confidence="low",
        limitations=[
            "provider live transport request plan is a descriptor only",
            "no provider request executor, network call, response payload, or runtime ingest is bound",
            "query window is date-only and request descriptors are hashed",
        ],
    )
    privacy = ScoutEnergyPrivacy()
    boundary = ScoutEnergyBoundary()
    plan_sha = aggregate_sha256(
        [
            preflight["sha256"],
            {
                "artifact": "provider_live_transport_request_plan",
                "query_window": query_window,
                "request_slots": [
                    {
                        "capability": slot["capability"],
                        "provider_request_kind": slot["provider_request_kind"],
                        "request_descriptor_sha256": slot["request_descriptor_sha256"],
                    }
                    for slot in request_slots
                ],
                "transport_mode": "request_plan_only",
            },
        ]
    )
    return {
        "artifact_kind": "scout_wearable_provider_live_transport_request_plan",
        "artifact_version": "wearable_provider_live_transport_request_plan.v1",
        "source_provider": provider,
        "source_path": str(preflight_path),
        "sha256": plan_sha,
        "preflight": {
            "artifact_kind": preflight["artifact_kind"],
            "source_provider": preflight["source_provider"],
            "source_path": preflight["source_path"],
            "sha256": preflight["sha256"],
        },
        "authorization_digest": {
            "account_authorized": preflight["authorization"]["account_authorized"],
            "explicit_consent": preflight["authorization"]["explicit_consent"],
            "account_ref_sha256": preflight["authorization"]["account_ref_sha256"],
            "device_ref_sha256": preflight["authorization"]["device_ref_sha256"],
            "token_ref_sha256": preflight["authorization"]["token_ref_sha256"],
            "token_value_exposed": False,
            "normalized_scopes": preflight["authorization"]["normalized_scopes"],
        },
        "query_window": query_window,
        "request_slots": request_slots,
        "transport": {
            "transport_mode": "request_plan_only",
            "request_executor_bound": False,
            "network_request_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "raw_response_committed": False,
        },
        "data_quality": data_quality.model_dump(mode="json"),
        "privacy": privacy.model_dump(mode="json"),
        "boundary": boundary.model_dump(mode="json"),
        "mutation": {
            "source_file_mutated": False,
            "network_request_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "phase1_runtime_mutated": False,
            "safety_api_called": False,
            "raw_payload_committed": False,
            "raw_health_payload_shared": False,
            "raw_track_shared": False,
            "exact_timestamps_shared": False,
        },
    }


def write_provider_live_transport_request_plan(
    *,
    preflight_path: Path,
    output_path: Path,
    window_start_date: str,
    window_end_date: str,
    requested_capabilities: list[str] | None = None,
) -> dict[str, Any]:
    plan = build_provider_live_transport_request_plan(
        preflight_path=preflight_path,
        window_start_date=window_start_date,
        window_end_date=window_end_date,
        requested_capabilities=requested_capabilities,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "artifact_kind": "scout_wearable_provider_live_transport_request_plan_result",
        "artifact_version": "wearable_provider_live_transport_request_plan_result.v1",
        "source_provider": plan["source_provider"],
        "source_path": plan["source_path"],
        "sha256": plan["sha256"],
        "request_plan_path": str(output_path),
        "request_plan": plan,
        "data_quality": plan["data_quality"],
        "privacy": plan["privacy"],
        "boundary": plan["boundary"],
        "mutation": {
            "request_plan_artifact_written": True,
            "source_file_mutated": False,
            "network_request_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "phase1_runtime_mutated": False,
            "safety_api_called": False,
            "raw_payload_committed": False,
            "raw_health_payload_shared": False,
            "raw_track_shared": False,
            "exact_timestamps_shared": False,
        },
    }


def write_provider_live_executor_registration(
    *,
    preflight_path: Path,
    output_path: Path | None = None,
    executor_kind: ProviderLiveExecutorKind,
    executor_ref: str,
    supported_capabilities: list[str],
) -> dict[str, Any]:
    preflight = _load_preflight_artifact(preflight_path)
    _assert_preflight_artifact_safe(preflight)
    registration = _provider_live_executor_registration_artifact(
        preflight=preflight,
        preflight_path=preflight_path,
        executor_kind=executor_kind,
        executor_ref=executor_ref,
        supported_capabilities=supported_capabilities,
    )
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(registration, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return {
        "artifact_kind": "scout_wearable_provider_live_executor_registration_result",
        "artifact_version": "wearable_provider_live_executor_registration_result.v1",
        "source_provider": registration["source_provider"],
        "source_path": registration["source_path"],
        "sha256": registration["sha256"],
        "executor_registration_path": str(output_path) if output_path else None,
        "executor_registration": registration,
        "data_quality": registration["data_quality"],
        "privacy": registration["privacy"],
        "boundary": registration["boundary"],
        "mutation": {
            "executor_registration_artifact_written": output_path is not None,
            "source_file_mutated": False,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "phase1_runtime_mutated": False,
            "safety_api_called": False,
            "raw_payload_committed": False,
            "raw_health_payload_shared": False,
            "raw_track_shared": False,
            "exact_timestamps_shared": False,
        },
    }


def write_provider_live_executor_readiness(
    *,
    request_plan_path: Path,
    executor_registration_path: Path | None = None,
    output_path: Path | None = None,
) -> dict[str, Any]:
    request_plan = _load_request_plan_artifact(request_plan_path)
    _assert_request_plan_artifact_safe(request_plan)
    executor_registration = None
    if executor_registration_path is not None:
        executor_registration = _load_executor_registration_artifact(executor_registration_path)
        _assert_executor_registration_artifact_safe(executor_registration)
        _assert_executor_registration_matches_request_plan(
            executor_registration,
            request_plan=request_plan,
        )
    readiness = _provider_live_executor_readiness_artifact(
        request_plan=request_plan,
        request_plan_path=request_plan_path,
        executor_registration=executor_registration,
        executor_registration_path=executor_registration_path,
    )
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(readiness, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return {
        "artifact_kind": "scout_wearable_provider_live_executor_readiness_result",
        "artifact_version": "wearable_provider_live_executor_readiness_result.v1",
        "source_provider": readiness["source_provider"],
        "source_path": readiness["source_path"],
        "sha256": readiness["sha256"],
        "executor_readiness_path": str(output_path) if output_path else None,
        "executor_readiness": readiness,
        "data_quality": readiness["data_quality"],
        "privacy": readiness["privacy"],
        "boundary": readiness["boundary"],
        "mutation": {
            "executor_readiness_artifact_written": output_path is not None,
            "source_file_mutated": False,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "phase1_runtime_mutated": False,
            "safety_api_called": False,
            "raw_payload_committed": False,
            "raw_health_payload_shared": False,
            "raw_track_shared": False,
            "exact_timestamps_shared": False,
        },
    }


def write_provider_live_executor_handoff_package(
    *,
    request_plan_path: Path,
    executor_registration_path: Path,
    output_path: Path | None = None,
) -> dict[str, Any]:
    request_plan = _load_request_plan_artifact(request_plan_path)
    _assert_request_plan_artifact_safe(request_plan)
    executor_registration = _load_executor_registration_artifact(executor_registration_path)
    _assert_executor_registration_artifact_safe(executor_registration)
    _assert_executor_registration_matches_request_plan(
        executor_registration,
        request_plan=request_plan,
    )
    readiness = _provider_live_executor_readiness_artifact(
        request_plan=request_plan,
        request_plan_path=request_plan_path,
        executor_registration=executor_registration,
        executor_registration_path=executor_registration_path,
    )
    handoff = _provider_live_executor_handoff_package_artifact(
        request_plan=request_plan,
        request_plan_path=request_plan_path,
        executor_registration=executor_registration,
        executor_registration_path=executor_registration_path,
        readiness=readiness,
    )
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(handoff, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return {
        "artifact_kind": "scout_wearable_provider_live_executor_handoff_package_result",
        "artifact_version": "wearable_provider_live_executor_handoff_package_result.v1",
        "source_provider": handoff["source_provider"],
        "source_path": handoff["source_path"],
        "sha256": handoff["sha256"],
        "executor_handoff_path": str(output_path) if output_path else None,
        "executor_handoff": handoff,
        "data_quality": handoff["data_quality"],
        "privacy": handoff["privacy"],
        "boundary": handoff["boundary"],
        "mutation": {
            "executor_handoff_artifact_written": output_path is not None,
            "source_file_mutated": False,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "phase1_runtime_mutated": False,
            "safety_api_called": False,
            "raw_payload_committed": False,
            "raw_health_payload_shared": False,
            "raw_track_shared": False,
            "exact_timestamps_shared": False,
        },
    }


def write_provider_live_executor_handoff_outbox_index(
    *,
    outbox_dir: Path,
    output_path: Path | None = None,
) -> dict[str, Any]:
    if not outbox_dir.exists() or not outbox_dir.is_dir():
        raise FileNotFoundError(f"provider live executor handoff outbox not found: {outbox_dir}")
    entries = [
        _executor_handoff_outbox_index_entry(path)
        for path in sorted(outbox_dir.glob("*.json"))
        if path.is_file()
    ]
    eligible_entries = [
        entry for entry in entries if entry["eligible_for_executor_pickup_precheck"]
    ]
    providers = sorted(
        {
            entry["source_provider"]
            for entry in eligible_entries
            if entry.get("source_provider")
        }
    )
    source_provider = providers[0] if len(providers) == 1 else "mixed_provider"
    data_quality = ScoutEnergyDataQuality(
        heart_rate_confidence="low",
        gps_confidence="low",
        provider_value_confidence="low",
        limitations=[
            "provider live executor handoff outbox index scans local handoff packages only",
            "eligible entries verify handoff, request-plan, and executor-registration sha256 references",
            "outbox index is local external-executor pickup evidence, not live execution",
            "no network request, provider API call, remote upload, or runtime ingest is performed",
        ],
    )
    privacy = ScoutEnergyPrivacy()
    boundary = ScoutEnergyBoundary()
    index_sha = aggregate_sha256(
        [
            {
                "artifact": "provider_live_executor_handoff_outbox_index",
                "outbox_dir": str(outbox_dir),
                "entries": [
                    {
                        "source_path": entry["source_path"],
                        "file_sha256": entry["file_sha256"],
                        "eligible_for_executor_pickup_precheck": entry[
                            "eligible_for_executor_pickup_precheck"
                        ],
                    }
                    for entry in entries
                ],
                "transport_mode": "executor_handoff_outbox_index_only",
            }
        ]
    )
    outbox_index = {
        "artifact_kind": "scout_wearable_provider_live_executor_handoff_outbox_index",
        "artifact_version": "wearable_provider_live_executor_handoff_outbox_index.v1",
        "source_provider": source_provider,
        "source_path": str(outbox_dir),
        "sha256": index_sha,
        "outbox": {
            "source_path": str(outbox_dir),
            "json_file_count": len(entries),
            "eligible_handoff_count": len(eligible_entries),
            "rejected_file_count": len(entries) - len(eligible_entries),
        },
        "handoff_packages": entries,
        "transport": {
            "transport_mode": "executor_handoff_outbox_index_only",
            "request_executor_bound": False,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "raw_response_committed": False,
        },
        "data_quality": data_quality.model_dump(mode="json"),
        "privacy": privacy.model_dump(mode="json"),
        "boundary": boundary.model_dump(mode="json"),
        "mutation": {
            "source_file_mutated": False,
            "outbox_file_mutated": False,
            "outbox_file_moved": False,
            "outbox_file_deleted": False,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "phase1_runtime_mutated": False,
            "safety_api_called": False,
            "raw_payload_committed": False,
            "raw_health_payload_shared": False,
            "raw_track_shared": False,
            "exact_timestamps_shared": False,
        },
    }
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(outbox_index, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return {
        "artifact_kind": "scout_wearable_provider_live_executor_handoff_outbox_index_result",
        "artifact_version": "wearable_provider_live_executor_handoff_outbox_index_result.v1",
        "source_provider": outbox_index["source_provider"],
        "source_path": outbox_index["source_path"],
        "sha256": outbox_index["sha256"],
        "executor_handoff_outbox_index_path": str(output_path) if output_path else None,
        "executor_handoff_outbox_index": outbox_index,
        "data_quality": outbox_index["data_quality"],
        "privacy": outbox_index["privacy"],
        "boundary": outbox_index["boundary"],
        "mutation": {
            "executor_handoff_outbox_index_artifact_written": output_path is not None,
            "source_file_mutated": False,
            "outbox_file_mutated": False,
            "outbox_file_moved": False,
            "outbox_file_deleted": False,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "phase1_runtime_mutated": False,
            "safety_api_called": False,
            "raw_payload_committed": False,
            "raw_health_payload_shared": False,
            "raw_track_shared": False,
            "exact_timestamps_shared": False,
        },
    }


def write_provider_live_executor_handoff_pickup_manifest(
    *,
    outbox_index_path: Path,
    output_path: Path | None = None,
    handoff_source_path: Path | None = None,
) -> dict[str, Any]:
    outbox_index = _load_executor_handoff_outbox_index(outbox_index_path)
    _assert_executor_handoff_outbox_index_safe(outbox_index)
    selected_entry = _select_executor_handoff_outbox_entry(
        outbox_index,
        handoff_source_path=handoff_source_path,
    )
    selected_path = Path(selected_entry["source_path"])
    if sha256_file(selected_path) != selected_entry["file_sha256"]:
        raise ValueError("executor handoff outbox selected file sha256 mismatch")
    handoff_package = _load_executor_handoff_package_artifact(selected_path)
    _assert_executor_handoff_package_artifact_safe(handoff_package)
    if handoff_package["sha256"] != selected_entry["handoff_package_sha256"]:
        raise ValueError("executor handoff outbox selected handoff sha256 mismatch")

    pickup = _provider_live_executor_handoff_pickup_manifest_artifact(
        outbox_index=outbox_index,
        outbox_index_path=outbox_index_path,
        selected_entry=selected_entry,
        handoff_package=handoff_package,
    )
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(pickup, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return {
        "artifact_kind": "scout_wearable_provider_live_executor_handoff_pickup_manifest_result",
        "artifact_version": "wearable_provider_live_executor_handoff_pickup_manifest_result.v1",
        "source_provider": pickup["source_provider"],
        "source_path": pickup["source_path"],
        "sha256": pickup["sha256"],
        "executor_handoff_pickup_manifest_path": str(output_path) if output_path else None,
        "executor_handoff_path": selected_entry["source_path"],
        "executor_handoff_pickup_manifest": pickup,
        "data_quality": pickup["data_quality"],
        "privacy": pickup["privacy"],
        "boundary": pickup["boundary"],
        "mutation": {
            "executor_handoff_pickup_manifest_artifact_written": output_path is not None,
            "source_file_mutated": False,
            "outbox_file_mutated": False,
            "outbox_file_moved": False,
            "outbox_file_deleted": False,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "phase1_runtime_mutated": False,
            "safety_api_called": False,
            "raw_payload_committed": False,
            "raw_health_payload_shared": False,
            "raw_track_shared": False,
            "exact_timestamps_shared": False,
        },
    }


def write_provider_live_executor_handoff_fixture_replay(
    *,
    handoff_package_path: Path,
    response_fixture_path: Path,
    output_path: Path | None = None,
) -> dict[str, Any]:
    handoff_package = _load_executor_handoff_package_artifact(handoff_package_path)
    _assert_executor_handoff_package_artifact_safe(handoff_package)
    request_plan_path = Path(handoff_package["request_plan"]["source_path"])
    executor_registration_path = Path(handoff_package["executor_registration"]["source_path"])
    request_plan = _load_request_plan_artifact(request_plan_path)
    _assert_request_plan_artifact_safe(request_plan)
    executor_registration = _load_executor_registration_artifact(executor_registration_path)
    _assert_executor_registration_artifact_safe(executor_registration)
    _assert_executor_registration_matches_request_plan(
        executor_registration,
        request_plan=request_plan,
    )
    readiness = _provider_live_executor_readiness_artifact(
        request_plan=request_plan,
        request_plan_path=request_plan_path,
        executor_registration=executor_registration,
        executor_registration_path=executor_registration_path,
    )
    _assert_executor_handoff_package_matches_sources(
        handoff_package,
        handoff_package_path=handoff_package_path,
        request_plan=request_plan,
        request_plan_path=request_plan_path,
        executor_registration=executor_registration,
        executor_registration_path=executor_registration_path,
        readiness=readiness,
    )
    replay = _provider_live_executor_fixture_replay_artifact(
        request_plan=request_plan,
        request_plan_path=request_plan_path,
        executor_registration=executor_registration,
        executor_registration_path=executor_registration_path,
        readiness=readiness,
        response_fixture_path=response_fixture_path,
        handoff_package=handoff_package,
        handoff_package_path=handoff_package_path,
    )
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(replay, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return {
        "artifact_kind": "scout_wearable_provider_live_executor_handoff_fixture_replay_result",
        "artifact_version": "wearable_provider_live_executor_handoff_fixture_replay_result.v1",
        "source_provider": replay["source_provider"],
        "source_path": replay["source_path"],
        "sha256": replay["sha256"],
        "executor_handoff_path": str(handoff_package_path),
        "executor_fixture_replay_path": str(output_path) if output_path else None,
        "executor_fixture_replay": replay,
        "data_quality": replay["data_quality"],
        "privacy": replay["privacy"],
        "boundary": replay["boundary"],
        "mutation": {
            "handoff_fixture_replay_artifact_written": output_path is not None,
            "source_file_mutated": False,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "phase1_runtime_mutated": False,
            "safety_api_called": False,
            "raw_payload_committed": False,
            "raw_health_payload_shared": False,
            "raw_track_shared": False,
            "exact_timestamps_shared": False,
        },
    }


def write_provider_live_executor_response_manifest(
    *,
    handoff_package_path: Path,
    response_payload_path: Path,
    output_path: Path | None = None,
) -> dict[str, Any]:
    handoff_package = _load_executor_handoff_package_artifact(handoff_package_path)
    _assert_executor_handoff_package_artifact_safe(handoff_package)
    request_plan_path = Path(handoff_package["request_plan"]["source_path"])
    executor_registration_path = Path(handoff_package["executor_registration"]["source_path"])
    request_plan = _load_request_plan_artifact(request_plan_path)
    _assert_request_plan_artifact_safe(request_plan)
    executor_registration = _load_executor_registration_artifact(executor_registration_path)
    _assert_executor_registration_artifact_safe(executor_registration)
    _assert_executor_registration_matches_request_plan(
        executor_registration,
        request_plan=request_plan,
    )
    readiness = _provider_live_executor_readiness_artifact(
        request_plan=request_plan,
        request_plan_path=request_plan_path,
        executor_registration=executor_registration,
        executor_registration_path=executor_registration_path,
    )
    _assert_executor_handoff_package_matches_sources(
        handoff_package,
        handoff_package_path=handoff_package_path,
        request_plan=request_plan,
        request_plan_path=request_plan_path,
        executor_registration=executor_registration,
        executor_registration_path=executor_registration_path,
        readiness=readiness,
    )
    manifest = _provider_live_executor_response_manifest_artifact(
        handoff_package=handoff_package,
        handoff_package_path=handoff_package_path,
        response_payload_path=response_payload_path,
    )
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return {
        "artifact_kind": "scout_wearable_provider_live_executor_response_manifest_result",
        "artifact_version": "wearable_provider_live_executor_response_manifest_result.v1",
        "source_provider": manifest["source_provider"],
        "source_path": manifest["source_path"],
        "sha256": manifest["sha256"],
        "executor_response_manifest_path": str(output_path) if output_path else None,
        "executor_response_manifest": manifest,
        "data_quality": manifest["data_quality"],
        "privacy": manifest["privacy"],
        "boundary": manifest["boundary"],
        "mutation": {
            "executor_response_manifest_artifact_written": output_path is not None,
            "source_file_mutated": False,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "phase1_runtime_mutated": False,
            "safety_api_called": False,
            "raw_payload_committed": False,
            "raw_health_payload_shared": False,
            "raw_track_shared": False,
            "exact_timestamps_shared": False,
        },
    }


def write_provider_live_executor_pickup_response_manifest(
    *,
    pickup_manifest_path: Path,
    response_payload_path: Path,
    output_path: Path | None = None,
) -> dict[str, Any]:
    pickup_manifest = _load_executor_handoff_pickup_manifest_artifact(pickup_manifest_path)
    _assert_executor_handoff_pickup_manifest_artifact_safe(pickup_manifest)
    handoff_package_path = Path(pickup_manifest["selected_handoff"]["source_path"])
    if sha256_file(handoff_package_path) != pickup_manifest["selected_handoff"]["file_sha256"]:
        raise ValueError("executor pickup response manifest handoff file sha256 mismatch")
    handoff_package = _load_executor_handoff_package_artifact(handoff_package_path)
    _assert_executor_handoff_package_artifact_safe(handoff_package)
    if handoff_package["sha256"] != pickup_manifest["selected_handoff"]["sha256"]:
        raise ValueError("executor pickup response manifest handoff artifact sha256 mismatch")
    request_plan_path = Path(handoff_package["request_plan"]["source_path"])
    executor_registration_path = Path(handoff_package["executor_registration"]["source_path"])
    request_plan = _load_request_plan_artifact(request_plan_path)
    _assert_request_plan_artifact_safe(request_plan)
    executor_registration = _load_executor_registration_artifact(executor_registration_path)
    _assert_executor_registration_artifact_safe(executor_registration)
    _assert_executor_registration_matches_request_plan(
        executor_registration,
        request_plan=request_plan,
    )
    readiness = _provider_live_executor_readiness_artifact(
        request_plan=request_plan,
        request_plan_path=request_plan_path,
        executor_registration=executor_registration,
        executor_registration_path=executor_registration_path,
    )
    _assert_executor_handoff_package_matches_sources(
        handoff_package,
        handoff_package_path=handoff_package_path,
        request_plan=request_plan,
        request_plan_path=request_plan_path,
        executor_registration=executor_registration,
        executor_registration_path=executor_registration_path,
        readiness=readiness,
    )
    manifest = _provider_live_executor_response_manifest_artifact(
        handoff_package=handoff_package,
        handoff_package_path=handoff_package_path,
        response_payload_path=response_payload_path,
        pickup_manifest=pickup_manifest,
        pickup_manifest_path=pickup_manifest_path,
    )
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return {
        "artifact_kind": "scout_wearable_provider_live_executor_pickup_response_manifest_result",
        "artifact_version": "wearable_provider_live_executor_pickup_response_manifest_result.v1",
        "source_provider": manifest["source_provider"],
        "source_path": manifest["source_path"],
        "sha256": manifest["sha256"],
        "executor_response_manifest_path": str(output_path) if output_path else None,
        "executor_handoff_pickup_manifest_path": str(pickup_manifest_path),
        "executor_response_manifest": manifest,
        "data_quality": manifest["data_quality"],
        "privacy": manifest["privacy"],
        "boundary": manifest["boundary"],
        "mutation": {
            "executor_response_manifest_artifact_written": output_path is not None,
            "source_file_mutated": False,
            "outbox_file_mutated": False,
            "outbox_file_moved": False,
            "outbox_file_deleted": False,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "phase1_runtime_mutated": False,
            "safety_api_called": False,
            "raw_payload_committed": False,
            "raw_health_payload_shared": False,
            "raw_track_shared": False,
            "exact_timestamps_shared": False,
        },
    }


def write_provider_live_executor_response_inbox_index(
    *,
    inbox_dir: Path,
    output_path: Path | None = None,
) -> dict[str, Any]:
    if not inbox_dir.exists() or not inbox_dir.is_dir():
        raise FileNotFoundError(f"provider live executor response inbox not found: {inbox_dir}")
    entries = [
        _executor_response_inbox_index_entry(path)
        for path in sorted(inbox_dir.glob("*.json"))
        if path.is_file()
    ]
    eligible_entries = [
        entry for entry in entries if entry["eligible_for_consumption_precheck"]
    ]
    providers = sorted(
        {
            entry["source_provider"]
            for entry in eligible_entries
            if entry.get("source_provider")
        }
    )
    source_provider = providers[0] if len(providers) == 1 else "mixed_provider"
    data_quality = ScoutEnergyDataQuality(
        heart_rate_confidence="low",
        gps_confidence="low",
        provider_value_confidence="low",
        limitations=[
            "provider live executor response inbox index scans local manifest files only",
            "eligible entries verify manifest, handoff, and response payload sha256 references",
            "full consumption still rechecks the manifest before sanitization and Energy Reserve build",
            "no network request, provider API call, remote upload, or runtime ingest is performed",
        ],
    )
    privacy = ScoutEnergyPrivacy()
    boundary = ScoutEnergyBoundary()
    index_sha = aggregate_sha256(
        [
            {
                "artifact": "provider_live_executor_response_inbox_index",
                "inbox_dir": str(inbox_dir),
                "entries": [
                    {
                        "source_path": entry["source_path"],
                        "file_sha256": entry["file_sha256"],
                        "eligible_for_consumption_precheck": entry["eligible_for_consumption_precheck"],
                    }
                    for entry in entries
                ],
                "transport_mode": "executor_response_inbox_index_only",
            }
        ]
    )
    inbox_index = {
        "artifact_kind": "scout_wearable_provider_live_executor_response_inbox_index",
        "artifact_version": "wearable_provider_live_executor_response_inbox_index.v1",
        "source_provider": source_provider,
        "source_path": str(inbox_dir),
        "sha256": index_sha,
        "inbox": {
            "source_path": str(inbox_dir),
            "json_file_count": len(entries),
            "eligible_manifest_count": len(eligible_entries),
            "rejected_manifest_count": len(entries) - len(eligible_entries),
        },
        "manifests": entries,
        "transport": {
            "transport_mode": "executor_response_inbox_index_only",
            "request_executor_bound": False,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "raw_response_committed": False,
        },
        "data_quality": data_quality.model_dump(mode="json"),
        "privacy": privacy.model_dump(mode="json"),
        "boundary": boundary.model_dump(mode="json"),
        "mutation": {
            "source_file_mutated": False,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "phase1_runtime_mutated": False,
            "safety_api_called": False,
            "raw_payload_committed": False,
            "raw_health_payload_shared": False,
            "raw_track_shared": False,
            "exact_timestamps_shared": False,
        },
    }
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(inbox_index, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return {
        "artifact_kind": "scout_wearable_provider_live_executor_response_inbox_index_result",
        "artifact_version": "wearable_provider_live_executor_response_inbox_index_result.v1",
        "source_provider": inbox_index["source_provider"],
        "source_path": inbox_index["source_path"],
        "sha256": inbox_index["sha256"],
        "executor_response_inbox_index_path": str(output_path) if output_path else None,
        "executor_response_inbox_index": inbox_index,
        "data_quality": inbox_index["data_quality"],
        "privacy": inbox_index["privacy"],
        "boundary": inbox_index["boundary"],
        "mutation": {
            "executor_response_inbox_index_artifact_written": output_path is not None,
            "source_file_mutated": False,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "phase1_runtime_mutated": False,
            "safety_api_called": False,
            "raw_payload_committed": False,
            "raw_health_payload_shared": False,
            "raw_track_shared": False,
            "exact_timestamps_shared": False,
        },
    }


def write_provider_live_executor_fixture_replay(
    *,
    request_plan_path: Path,
    executor_registration_path: Path,
    response_fixture_path: Path,
    output_path: Path | None = None,
) -> dict[str, Any]:
    request_plan = _load_request_plan_artifact(request_plan_path)
    _assert_request_plan_artifact_safe(request_plan)
    executor_registration = _load_executor_registration_artifact(executor_registration_path)
    _assert_executor_registration_artifact_safe(executor_registration)
    _assert_executor_registration_matches_request_plan(
        executor_registration,
        request_plan=request_plan,
    )
    readiness = _provider_live_executor_readiness_artifact(
        request_plan=request_plan,
        request_plan_path=request_plan_path,
        executor_registration=executor_registration,
        executor_registration_path=executor_registration_path,
    )
    replay = _provider_live_executor_fixture_replay_artifact(
        request_plan=request_plan,
        request_plan_path=request_plan_path,
        executor_registration=executor_registration,
        executor_registration_path=executor_registration_path,
        readiness=readiness,
        response_fixture_path=response_fixture_path,
    )
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(replay, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return {
        "artifact_kind": "scout_wearable_provider_live_executor_fixture_replay_result",
        "artifact_version": "wearable_provider_live_executor_fixture_replay_result.v1",
        "source_provider": replay["source_provider"],
        "source_path": replay["source_path"],
        "sha256": replay["sha256"],
        "executor_fixture_replay_path": str(output_path) if output_path else None,
        "executor_fixture_replay": replay,
        "data_quality": replay["data_quality"],
        "privacy": replay["privacy"],
        "boundary": replay["boundary"],
        "mutation": {
            "executor_fixture_replay_artifact_written": output_path is not None,
            "source_file_mutated": False,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "phase1_runtime_mutated": False,
            "safety_api_called": False,
            "raw_payload_committed": False,
            "raw_health_payload_shared": False,
            "raw_track_shared": False,
            "exact_timestamps_shared": False,
        },
    }


def write_provider_live_transport_response_admission_from_fixture_replay(
    *,
    fixture_replay_path: Path,
    output_dir: Path,
    activity_id_prefix: str,
    admitted_capabilities: list[str],
    admission_output_path: Path | None = None,
    activity_type: str = "hiking",
    overwrite: bool = False,
) -> dict[str, Any]:
    fixture_replay = _load_executor_fixture_replay_artifact(fixture_replay_path)
    _assert_executor_fixture_replay_artifact_safe(fixture_replay)
    response_fixture_path = Path(fixture_replay["response_fixture"]["source_path"])
    if sha256_file(response_fixture_path) != fixture_replay["response_fixture"]["sha256"]:
        raise ValueError("provider live replay admission response fixture sha256 mismatch")
    admission_result = write_provider_live_transport_response_admission(
        request_plan_path=Path(fixture_replay["request_plan"]["source_path"]),
        response_fixture_path=response_fixture_path,
        output_dir=output_dir,
        activity_id_prefix=activity_id_prefix,
        admitted_capabilities=admitted_capabilities,
        admission_output_path=admission_output_path,
        activity_type=activity_type,
        overwrite=overwrite,
    )
    return {
        "artifact_kind": "scout_wearable_provider_live_executor_replay_admission_result",
        "artifact_version": "wearable_provider_live_executor_replay_admission_result.v1",
        "source_provider": admission_result["source_provider"],
        "source_path": str(fixture_replay_path),
        "sha256": aggregate_sha256(
            [
                fixture_replay["sha256"],
                admission_result["sha256"],
                {
                    "artifact": "provider_live_executor_replay_admission",
                    "transport_mode": "executor_replay_admission_only",
                },
            ]
        ),
        "executor_fixture_replay": {
            "artifact_kind": fixture_replay["artifact_kind"],
            "source_provider": fixture_replay["source_provider"],
            "source_path": str(fixture_replay_path),
            "sha256": fixture_replay["sha256"],
        },
        "admission_path": admission_result["admission_path"],
        "sanitized_import_paths": admission_result["sanitized_import_paths"],
        "admission": admission_result["admission"],
        "transport": {
            "transport_mode": "executor_replay_admission_only",
            "request_executor_bound": False,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "raw_response_committed": False,
        },
        "data_quality": admission_result["data_quality"],
        "privacy": admission_result["privacy"],
        "boundary": admission_result["boundary"],
        "mutation": {
            "response_admission_artifact_written": admission_output_path is not None,
            "sanitized_imports_written": True,
            "source_file_mutated": False,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "phase1_runtime_mutated": False,
            "safety_api_called": False,
            "raw_payload_committed": False,
            "raw_health_payload_shared": False,
            "raw_track_shared": False,
            "exact_timestamps_shared": False,
        },
    }


def write_provider_live_transport_response_admission_from_executor_response_manifest(
    *,
    executor_response_manifest_path: Path,
    output_dir: Path,
    activity_id_prefix: str,
    admitted_capabilities: list[str],
    admission_output_path: Path | None = None,
    activity_type: str = "hiking",
    overwrite: bool = False,
) -> dict[str, Any]:
    manifest = _load_executor_response_manifest_artifact(executor_response_manifest_path)
    _assert_executor_response_manifest_artifact_safe(manifest)
    handoff_package_path = Path(manifest["handoff_package"]["source_path"])
    handoff_package = _load_executor_handoff_package_artifact(handoff_package_path)
    _assert_executor_handoff_package_artifact_safe(handoff_package)
    if handoff_package["sha256"] != manifest["handoff_package"]["sha256"]:
        raise ValueError("provider live executor response manifest handoff sha256 mismatch")
    response_payload_path = Path(manifest["response_payload"]["source_path"])
    if sha256_file(response_payload_path) != manifest["response_payload"]["sha256"]:
        raise ValueError("provider live executor response manifest payload sha256 mismatch")
    request_plan_path = Path(handoff_package["request_plan"]["source_path"])
    executor_registration_path = Path(handoff_package["executor_registration"]["source_path"])
    request_plan = _load_request_plan_artifact(request_plan_path)
    _assert_request_plan_artifact_safe(request_plan)
    executor_registration = _load_executor_registration_artifact(executor_registration_path)
    _assert_executor_registration_artifact_safe(executor_registration)
    _assert_executor_registration_matches_request_plan(
        executor_registration,
        request_plan=request_plan,
    )
    readiness = _provider_live_executor_readiness_artifact(
        request_plan=request_plan,
        request_plan_path=request_plan_path,
        executor_registration=executor_registration,
        executor_registration_path=executor_registration_path,
    )
    _assert_executor_handoff_package_matches_sources(
        handoff_package,
        handoff_package_path=handoff_package_path,
        request_plan=request_plan,
        request_plan_path=request_plan_path,
        executor_registration=executor_registration,
        executor_registration_path=executor_registration_path,
        readiness=readiness,
    )
    admission_result = write_provider_live_transport_response_admission(
        request_plan_path=request_plan_path,
        response_fixture_path=response_payload_path,
        output_dir=output_dir,
        activity_id_prefix=activity_id_prefix,
        admitted_capabilities=admitted_capabilities,
        admission_output_path=admission_output_path,
        activity_type=activity_type,
        overwrite=overwrite,
    )
    result = {
        "artifact_kind": "scout_wearable_provider_live_executor_response_manifest_admission_result",
        "artifact_version": "wearable_provider_live_executor_response_manifest_admission_result.v1",
        "source_provider": admission_result["source_provider"],
        "source_path": str(executor_response_manifest_path),
        "sha256": aggregate_sha256(
            [
                manifest["sha256"],
                admission_result["sha256"],
                {
                    "artifact": "provider_live_executor_response_manifest_admission",
                    "transport_mode": "executor_response_manifest_admission_only",
                },
            ]
        ),
        "executor_response_manifest": {
            "artifact_kind": manifest["artifact_kind"],
            "source_provider": manifest["source_provider"],
            "source_path": str(executor_response_manifest_path),
            "sha256": manifest["sha256"],
            "handoff_package_sha256": manifest["handoff_package"]["sha256"],
            "response_payload_sha256": manifest["response_payload"]["sha256"],
        },
        "admission_path": admission_result["admission_path"],
        "sanitized_import_paths": admission_result["sanitized_import_paths"],
        "admission": admission_result["admission"],
        "transport": {
            "transport_mode": "executor_response_manifest_admission_only",
            "request_executor_bound": False,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "raw_response_committed": False,
        },
        "data_quality": admission_result["data_quality"],
        "privacy": admission_result["privacy"],
        "boundary": admission_result["boundary"],
        "mutation": {
            "response_admission_artifact_written": admission_output_path is not None,
            "sanitized_imports_written": True,
            "source_file_mutated": False,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "phase1_runtime_mutated": False,
            "safety_api_called": False,
            "raw_payload_committed": False,
            "raw_health_payload_shared": False,
            "raw_track_shared": False,
            "exact_timestamps_shared": False,
        },
    }
    if "pickup_manifest" in manifest:
        result["executor_response_manifest"]["pickup_manifest_sha256"] = manifest[
            "pickup_manifest"
        ]["sha256"]
        result["executor_response_manifest"]["pickup_manifest_source_path"] = manifest[
            "pickup_manifest"
        ]["source_path"]
    return result


def write_provider_live_transport_response_admission(
    *,
    request_plan_path: Path,
    response_fixture_path: Path,
    output_dir: Path,
    activity_id_prefix: str,
    admitted_capabilities: list[str],
    admission_output_path: Path | None = None,
    activity_type: str = "hiking",
    overwrite: bool = False,
) -> dict[str, Any]:
    request_plan = _load_request_plan_artifact(request_plan_path)
    _assert_request_plan_artifact_safe(request_plan)
    admitted = _assert_response_capabilities_planned(
        admitted_capabilities,
        planned_capabilities=[slot["capability"] for slot in request_plan["request_slots"]],
    )
    if "activity_summary_import" not in admitted:
        raise ValueError("provider live response admission requires activity_summary_import capability")

    provider_fixture = _provider_fixture_for_live_provider(request_plan["source_provider"])
    sanitized_result = write_sanitized_import_batch_from_provider_api_fixture(
        response_fixture_path,
        provider=provider_fixture,
        output_dir=output_dir,
        activity_id_prefix=activity_id_prefix,
        explicit_consent=True,
        auth_token_ref=f"preflight-token-ref-sha256:{request_plan['authorization_digest']['token_ref_sha256']}",
        scopes=request_plan["authorization_digest"]["normalized_scopes"],
        activity_type=activity_type,
        overwrite=overwrite,
    )
    admission = _provider_live_transport_response_admission_artifact(
        request_plan=request_plan,
        request_plan_path=request_plan_path,
        response_fixture_path=response_fixture_path,
        provider_fixture=provider_fixture,
        admitted_capabilities=admitted,
        sanitized_result=sanitized_result,
    )
    if admission_output_path is not None:
        admission_output_path.parent.mkdir(parents=True, exist_ok=True)
        admission_output_path.write_text(
            json.dumps(admission, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return {
        "artifact_kind": "scout_wearable_provider_live_transport_response_admission_result",
        "artifact_version": "wearable_provider_live_transport_response_admission_result.v1",
        "source_provider": admission["source_provider"],
        "source_path": admission["source_path"],
        "sha256": admission["sha256"],
        "admission_path": str(admission_output_path) if admission_output_path else None,
        "sanitized_import_paths": sanitized_result["sanitized_import_paths"],
        "admission": admission,
        "data_quality": admission["data_quality"],
        "privacy": admission["privacy"],
        "boundary": admission["boundary"],
        "mutation": {
            "response_admission_artifact_written": admission_output_path is not None,
            "sanitized_imports_written": True,
            "source_file_mutated": False,
            "network_request_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "phase1_runtime_mutated": False,
            "safety_api_called": False,
            "raw_payload_committed": False,
            "raw_health_payload_shared": False,
            "raw_track_shared": False,
            "exact_timestamps_shared": False,
        },
    }


def write_provider_live_transport_materialization(
    *,
    admission_path: Path,
    output_dir: Path,
    materialization_output_path: Path | None = None,
    root: Path | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    admission = _load_response_admission_artifact(admission_path)
    _assert_response_admission_artifact_safe(admission)
    sanitized_paths = [
        Path(path)
        for path in admission.get("sanitized_import_result", {}).get("sanitized_import_paths", [])
    ]
    if not sanitized_paths:
        raise ValueError("provider live materialization requires sanitized import paths")
    normalization = write_normalized_wearable_imports(
        sanitized_paths,
        output_dir=output_dir,
        root=root,
        overwrite=overwrite,
    )
    materialization = _provider_live_transport_materialization_artifact(
        admission=admission,
        admission_path=admission_path,
        normalization=normalization,
    )
    if materialization_output_path is not None:
        materialization_output_path.parent.mkdir(parents=True, exist_ok=True)
        materialization_output_path.write_text(
            json.dumps(materialization, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return {
        "artifact_kind": "scout_wearable_provider_live_transport_materialization_result",
        "artifact_version": "wearable_provider_live_transport_materialization_result.v1",
        "source_provider": materialization["source_provider"],
        "source_path": materialization["source_path"],
        "sha256": materialization["sha256"],
        "materialization_path": str(materialization_output_path) if materialization_output_path else None,
        "normalized_paths": normalization["normalized_paths"],
        "normalization": normalization,
        "materialization": materialization,
        "data_quality": materialization["data_quality"],
        "privacy": materialization["privacy"],
        "boundary": materialization["boundary"],
        "mutation": {
            "materialization_artifact_written": materialization_output_path is not None,
            "normalized_summaries_written": True,
            "source_file_mutated": False,
            "network_request_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "phase1_runtime_mutated": False,
            "safety_api_called": False,
            "raw_payload_committed": False,
            "raw_health_payload_shared": False,
            "raw_track_shared": False,
            "exact_timestamps_shared": False,
        },
    }


def write_provider_live_transport_sync_package(
    *,
    materialization_path: Path,
    package_output_path: Path | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    materialization = _load_materialization_artifact(materialization_path)
    _assert_materialization_artifact_safe(materialization)
    normalized_paths = [
        Path(path)
        for path in materialization.get("normalization", {}).get("normalized_paths", [])
    ]
    if not normalized_paths:
        raise ValueError("provider live sync package requires normalized summary paths")
    normalized_summaries = _validated_normalized_summary_manifest(normalized_paths, root=root)
    sync_package = _provider_live_transport_sync_package_artifact(
        materialization=materialization,
        materialization_path=materialization_path,
        normalized_summaries=normalized_summaries,
    )
    if package_output_path is not None:
        package_output_path.parent.mkdir(parents=True, exist_ok=True)
        package_output_path.write_text(
            json.dumps(sync_package, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return {
        "artifact_kind": "scout_wearable_provider_live_transport_sync_package_result",
        "artifact_version": "wearable_provider_live_transport_sync_package_result.v1",
        "source_provider": sync_package["source_provider"],
        "source_path": sync_package["source_path"],
        "sha256": sync_package["sha256"],
        "sync_package_path": str(package_output_path) if package_output_path else None,
        "normalized_summary_count": sync_package["normalized_summary_count"],
        "normalized_summaries": normalized_summaries,
        "sync_package": sync_package,
        "data_quality": sync_package["data_quality"],
        "privacy": sync_package["privacy"],
        "boundary": sync_package["boundary"],
        "mutation": {
            "sync_package_artifact_written": package_output_path is not None,
            "source_file_mutated": False,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "phase1_runtime_mutated": False,
            "safety_api_called": False,
            "raw_payload_committed": False,
            "raw_health_payload_shared": False,
            "raw_track_shared": False,
            "exact_timestamps_shared": False,
        },
    }


def _assert_preflight_only(
    *,
    network_request_performed: bool,
    real_provider_api_called: bool,
    runtime_ingest_performed: bool,
) -> None:
    if network_request_performed:
        raise ValueError("preflight cannot perform network requests")
    if real_provider_api_called:
        raise ValueError("preflight cannot call a real provider API")
    if runtime_ingest_performed:
        raise ValueError("preflight cannot perform runtime ingest")


def _assert_credential_vault_reference_only(
    *,
    credential_values_loaded: bool,
    credential_values_exposed: bool,
    vault_lookup_performed: bool,
    vault_write_performed: bool,
    network_request_performed: bool,
    real_provider_api_called: bool,
    runtime_ingest_performed: bool,
) -> None:
    if credential_values_loaded:
        raise ValueError("credential vault reference cannot load credential values")
    if credential_values_exposed:
        raise ValueError("credential vault reference cannot expose credential values")
    if vault_lookup_performed:
        raise ValueError("credential vault reference cannot perform vault lookup")
    if vault_write_performed:
        raise ValueError("credential vault reference cannot perform vault write")
    if network_request_performed:
        raise ValueError("credential vault reference cannot perform network requests")
    if real_provider_api_called:
        raise ValueError("credential vault reference cannot call a real provider API")
    if runtime_ingest_performed:
        raise ValueError("credential vault reference cannot perform runtime ingest")


def _assert_connector_reference_only(
    *,
    connector_process_started: bool,
    connector_health_check_performed: bool,
    connector_live_request_performed: bool,
    credential_values_loaded: bool,
    credential_values_exposed: bool,
    network_request_performed: bool,
    real_provider_api_called: bool,
    runtime_ingest_performed: bool,
) -> None:
    if connector_process_started:
        raise ValueError("connector reference cannot start a connector process")
    if connector_health_check_performed:
        raise ValueError("connector reference cannot perform connector health checks")
    if connector_live_request_performed:
        raise ValueError("connector reference cannot perform live connector requests")
    if credential_values_loaded:
        raise ValueError("connector reference cannot load credential values")
    if credential_values_exposed:
        raise ValueError("connector reference cannot expose credential values")
    if network_request_performed:
        raise ValueError("connector reference cannot perform network requests")
    if real_provider_api_called:
        raise ValueError("connector reference cannot call a real provider API")
    if runtime_ingest_performed:
        raise ValueError("connector reference cannot perform runtime ingest")


def _assert_network_policy_reference_only(
    *,
    dns_lookup_performed: bool,
    network_socket_opened: bool,
    tls_handshake_performed: bool,
    http_request_performed: bool,
    network_request_performed: bool,
    real_provider_api_called: bool,
    remote_upload_performed: bool,
    runtime_ingest_performed: bool,
) -> None:
    if dns_lookup_performed:
        raise ValueError("network policy reference cannot perform DNS lookups")
    if network_socket_opened:
        raise ValueError("network policy reference cannot open network sockets")
    if tls_handshake_performed:
        raise ValueError("network policy reference cannot perform TLS handshakes")
    if http_request_performed:
        raise ValueError("network policy reference cannot perform HTTP requests")
    if network_request_performed:
        raise ValueError("network policy reference cannot perform network requests")
    if real_provider_api_called:
        raise ValueError("network policy reference cannot call a real provider API")
    if remote_upload_performed:
        raise ValueError("network policy reference cannot perform remote uploads")
    if runtime_ingest_performed:
        raise ValueError("network policy reference cannot perform runtime ingest")


def _assert_runtime_ingest_boundary_reference_only(
    *,
    runtime_ingest_performed: bool,
    runtime_write_performed: bool,
    phase1_runtime_mutated: bool,
    phase1_runtime_safety_truth: bool,
    safety_api_called: bool,
    network_request_performed: bool,
    real_provider_api_called: bool,
) -> None:
    if runtime_ingest_performed:
        raise ValueError("runtime ingest boundary reference cannot perform runtime ingest")
    if runtime_write_performed:
        raise ValueError("runtime ingest boundary reference cannot perform runtime writes")
    if phase1_runtime_mutated:
        raise ValueError("runtime ingest boundary reference cannot mutate Phase 1 runtime")
    if phase1_runtime_safety_truth:
        raise ValueError("runtime ingest boundary reference cannot assert Phase 1 safety truth")
    if safety_api_called:
        raise ValueError("runtime ingest boundary reference cannot call safety APIs")
    if network_request_performed:
        raise ValueError("runtime ingest boundary reference cannot perform network requests")
    if real_provider_api_called:
        raise ValueError("runtime ingest boundary reference cannot call a real provider API")


def _assert_phase1_safety_boundary_reference_only(
    *,
    phase1_runtime_mutated: bool,
    phase1_runtime_safety_truth: bool,
    phase1_l0_l4_state_mutated: bool,
    phase1_safety_state_mutation_allowed: bool,
    safety_api_called: bool,
    medical_diagnosis: bool,
    runtime_ingest_performed: bool,
    runtime_write_performed: bool,
    network_request_performed: bool,
    real_provider_api_called: bool,
    provider_values_are_scout_truth: bool,
) -> None:
    if phase1_runtime_mutated:
        raise ValueError("Phase 1 safety boundary reference cannot mutate Phase 1 runtime")
    if phase1_runtime_safety_truth:
        raise ValueError("Phase 1 safety boundary reference cannot assert Phase 1 safety truth")
    if phase1_l0_l4_state_mutated:
        raise ValueError("Phase 1 safety boundary reference cannot mutate L0-L4 state")
    if phase1_safety_state_mutation_allowed:
        raise ValueError("Phase 1 safety boundary reference cannot authorize Phase 1 state mutation")
    if safety_api_called:
        raise ValueError("Phase 1 safety boundary reference cannot call safety APIs")
    if medical_diagnosis:
        raise ValueError("Phase 1 safety boundary reference cannot perform medical diagnosis")
    if runtime_ingest_performed:
        raise ValueError("Phase 1 safety boundary reference cannot perform runtime ingest")
    if runtime_write_performed:
        raise ValueError("Phase 1 safety boundary reference cannot perform runtime writes")
    if network_request_performed:
        raise ValueError("Phase 1 safety boundary reference cannot perform network requests")
    if real_provider_api_called:
        raise ValueError("Phase 1 safety boundary reference cannot call a real provider API")
    if provider_values_are_scout_truth:
        raise ValueError("Phase 1 safety boundary reference cannot promote provider values to Scout truth")


def _provider_live_executor_registration_artifact(
    *,
    preflight: dict[str, Any],
    preflight_path: Path,
    executor_kind: ProviderLiveExecutorKind,
    executor_ref: str,
    supported_capabilities: list[str],
) -> dict[str, Any]:
    provider = preflight["source_provider"]
    expected_kind = _PROVIDER_EXECUTOR_KINDS[provider]
    if executor_kind != expected_kind:
        raise ValueError(f"provider live executor kind must be {expected_kind} for {provider}")
    if not executor_ref.strip():
        raise ValueError("provider live executor registration requires executor ref")
    allowed_capabilities = preflight["capability_review"]["allowed_capabilities"]
    _assert_capabilities_allowed(supported_capabilities, allowed_capabilities)
    capabilities = _dedupe([capability.strip() for capability in supported_capabilities if capability.strip()])
    data_quality = ScoutEnergyDataQuality(
        heart_rate_confidence="low",
        gps_confidence="low",
        provider_value_confidence="low",
        limitations=[
            "provider live executor registration stores local executor metadata only",
            "executor refs are represented only by sha256 digest",
            "no credentials are loaded, no network request is performed, and no provider API is called",
        ],
    )
    privacy = ScoutEnergyPrivacy()
    boundary = ScoutEnergyBoundary()
    registration_sha = aggregate_sha256(
        [
            preflight["sha256"],
            {
                "artifact": "provider_live_executor_registration",
                "executor_kind": executor_kind,
                "executor_ref_sha256": _sha256_text(executor_ref),
                "supported_capabilities": capabilities,
                "transport_mode": "executor_registration_only",
            },
        ]
    )
    return {
        "artifact_kind": "scout_wearable_provider_live_executor_registration",
        "artifact_version": "wearable_provider_live_executor_registration.v1",
        "source_provider": provider,
        "source_path": str(preflight_path),
        "sha256": registration_sha,
        "preflight": {
            "artifact_kind": preflight["artifact_kind"],
            "source_provider": preflight["source_provider"],
            "source_path": str(preflight_path),
            "sha256": preflight["sha256"],
        },
        "executor_registration": {
            "executor_registered": True,
            "executor_kind": executor_kind,
            "executor_ref_exposed": False,
            "executor_ref_sha256": _sha256_text(executor_ref),
            "supported_capabilities": capabilities,
            "credential_value_exposed": False,
            "live_provider_credentials_loaded": False,
        },
        "transport": {
            "transport_mode": "executor_registration_only",
            "request_executor_bound": False,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "raw_response_committed": False,
        },
        "data_quality": data_quality.model_dump(mode="json"),
        "privacy": privacy.model_dump(mode="json"),
        "boundary": boundary.model_dump(mode="json"),
        "mutation": {
            "source_file_mutated": False,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "phase1_runtime_mutated": False,
            "safety_api_called": False,
            "raw_payload_committed": False,
            "raw_health_payload_shared": False,
            "raw_track_shared": False,
            "exact_timestamps_shared": False,
        },
    }


def _provider_live_executor_readiness_artifact(
    *,
    request_plan: dict[str, Any],
    request_plan_path: Path,
    executor_registration: dict[str, Any] | None,
    executor_registration_path: Path | None,
) -> dict[str, Any]:
    request_slots = request_plan.get("request_slots", [])
    blockers = ["network_execution_disabled_by_local_contract"]
    if executor_registration is None:
        blockers.insert(0, "live_provider_executor_not_registered")
    registration_summary = _executor_registration_summary(
        executor_registration,
        executor_registration_path=executor_registration_path,
    )
    data_quality = ScoutEnergyDataQuality(
        heart_rate_confidence="low",
        gps_confidence="low",
        provider_value_confidence="low",
        limitations=[
            "provider live executor readiness is a local gate only",
            "no network request is performed and no provider API is called",
            "request descriptors are reviewed from the request plan without exposing request bodies",
        ],
    )
    privacy = ScoutEnergyPrivacy()
    boundary = ScoutEnergyBoundary()
    readiness_sha = aggregate_sha256(
        [
            request_plan["sha256"],
            {
                "artifact": "provider_live_executor_readiness",
                "ready_for_live_execution": False,
                "execution_blockers": blockers,
                "executor_registered": registration_summary["executor_registered"],
                "request_slot_count": len(request_slots),
                "transport_mode": "executor_readiness_only",
            },
        ]
    )
    return {
        "artifact_kind": "scout_wearable_provider_live_executor_readiness",
        "artifact_version": "wearable_provider_live_executor_readiness.v1",
        "source_provider": request_plan["source_provider"],
        "source_path": str(request_plan_path),
        "sha256": readiness_sha,
        "request_plan": {
            "artifact_kind": request_plan["artifact_kind"],
            "source_provider": request_plan["source_provider"],
            "source_path": str(request_plan_path),
            "sha256": request_plan["sha256"],
            "query_window": request_plan["query_window"],
        },
        "prerequisite_review": {
            "request_plan_valid": True,
            "account_authorized": request_plan["authorization_digest"]["account_authorized"],
            "explicit_consent": request_plan["authorization_digest"]["explicit_consent"],
            "token_value_exposed": False,
            "normalized_scopes": request_plan["authorization_digest"]["normalized_scopes"],
            "request_slot_count": len(request_slots),
            "capabilities": [slot["capability"] for slot in request_slots],
            "request_bodies_exposed": any(slot.get("request_body_exposed") for slot in request_slots),
            "raw_responses_committed": any(slot.get("raw_response_committed") for slot in request_slots),
        },
        "executor_registration": registration_summary,
        "ready_for_live_execution": False,
        "execution_blockers": blockers,
        "transport": {
            "transport_mode": "executor_readiness_only",
            "request_executor_bound": False,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "raw_response_committed": False,
        },
        "data_quality": data_quality.model_dump(mode="json"),
        "privacy": privacy.model_dump(mode="json"),
        "boundary": boundary.model_dump(mode="json"),
        "mutation": {
            "source_file_mutated": False,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "phase1_runtime_mutated": False,
            "safety_api_called": False,
            "raw_payload_committed": False,
            "raw_health_payload_shared": False,
            "raw_track_shared": False,
            "exact_timestamps_shared": False,
        },
    }


def _provider_live_executor_handoff_package_artifact(
    *,
    request_plan: dict[str, Any],
    request_plan_path: Path,
    executor_registration: dict[str, Any],
    executor_registration_path: Path,
    readiness: dict[str, Any],
) -> dict[str, Any]:
    request_descriptors = [
        {
            "capability": slot["capability"],
            "provider_request_kind": slot["provider_request_kind"],
            "provider_endpoint_ref": slot["provider_endpoint_ref"],
            "required_scopes": slot["required_scopes"],
            "available_scopes": slot["available_scopes"],
            "request_descriptor_sha256": slot["request_descriptor_sha256"],
            "request_body_exposed": False,
            "raw_response_committed": False,
            "normalized_output_target": slot["normalized_output_target"],
        }
        for slot in request_plan["request_slots"]
    ]
    data_quality = ScoutEnergyDataQuality(
        heart_rate_confidence="low",
        gps_confidence="low",
        provider_value_confidence="low",
        limitations=[
            "provider live executor handoff package is a local descriptor only",
            "no credentials, request bodies, provider responses, network calls, or runtime ingest are included",
            "network execution remains disabled by local contract",
        ],
    )
    privacy = ScoutEnergyPrivacy()
    boundary = ScoutEnergyBoundary()
    handoff_sha = aggregate_sha256(
        [
            request_plan["sha256"],
            executor_registration["sha256"],
            readiness["sha256"],
            {
                "artifact": "provider_live_executor_handoff_package",
                "request_descriptor_count": len(request_descriptors),
                "transport_mode": "executor_handoff_package_only",
            },
        ]
    )
    return {
        "artifact_kind": "scout_wearable_provider_live_executor_handoff_package",
        "artifact_version": "wearable_provider_live_executor_handoff_package.v1",
        "source_provider": request_plan["source_provider"],
        "source_path": f"{request_plan_path}+{executor_registration_path}",
        "sha256": handoff_sha,
        "request_plan": {
            "artifact_kind": request_plan["artifact_kind"],
            "source_provider": request_plan["source_provider"],
            "source_path": str(request_plan_path),
            "sha256": request_plan["sha256"],
            "query_window": request_plan["query_window"],
        },
        "executor_registration": {
            "artifact_kind": executor_registration["artifact_kind"],
            "source_provider": executor_registration["source_provider"],
            "source_path": str(executor_registration_path),
            "sha256": executor_registration["sha256"],
            "executor_kind": executor_registration["executor_registration"]["executor_kind"],
            "executor_ref_exposed": False,
            "executor_ref_sha256": executor_registration["executor_registration"]["executor_ref_sha256"],
            "credential_value_exposed": False,
            "live_provider_credentials_loaded": False,
            "supported_capabilities": executor_registration["executor_registration"]["supported_capabilities"],
        },
        "readiness": {
            "artifact_kind": readiness["artifact_kind"],
            "source_provider": readiness["source_provider"],
            "source_path": readiness["source_path"],
            "sha256": readiness["sha256"],
            "ready_for_live_execution": readiness["ready_for_live_execution"],
            "execution_blockers": readiness["execution_blockers"],
        },
        "request_descriptor_count": len(request_descriptors),
        "request_descriptors": request_descriptors,
        "transport": {
            "transport_mode": "executor_handoff_package_only",
            "request_executor_bound": False,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "raw_response_committed": False,
        },
        "data_quality": data_quality.model_dump(mode="json"),
        "privacy": privacy.model_dump(mode="json"),
        "boundary": boundary.model_dump(mode="json"),
        "mutation": {
            "source_file_mutated": False,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "phase1_runtime_mutated": False,
            "safety_api_called": False,
            "raw_payload_committed": False,
            "raw_health_payload_shared": False,
            "raw_track_shared": False,
            "exact_timestamps_shared": False,
        },
    }


def _provider_live_executor_fixture_replay_artifact(
    *,
    request_plan: dict[str, Any],
    request_plan_path: Path,
    executor_registration: dict[str, Any],
    executor_registration_path: Path,
    readiness: dict[str, Any],
    response_fixture_path: Path,
    handoff_package: dict[str, Any] | None = None,
    handoff_package_path: Path | None = None,
) -> dict[str, Any]:
    response_sha = sha256_file(response_fixture_path)
    limitations = [
        "provider live executor fixture replay uses a local response fixture only",
        "response fixture is referenced by path and sha256 but raw payload is not embedded",
        "no network request, provider API call, remote upload, or runtime ingest is performed",
    ]
    replay_sha_inputs: list[Any] = [
        request_plan["sha256"],
        executor_registration["sha256"],
        readiness["sha256"],
        response_sha,
        {
            "artifact": "provider_live_executor_fixture_replay",
            "transport_mode": "executor_fixture_replay_only",
        },
    ]
    source_path = f"{request_plan_path}+{executor_registration_path}+{response_fixture_path}"
    if handoff_package is not None:
        replay_sha_inputs.append(handoff_package["sha256"])
        source_path = f"{handoff_package_path}+{response_fixture_path}"
        limitations.append("fixture replay consumed a validated executor handoff package")
    data_quality = ScoutEnergyDataQuality(
        heart_rate_confidence="low",
        gps_confidence="low",
        provider_value_confidence="low",
        limitations=limitations,
    )
    privacy = ScoutEnergyPrivacy()
    boundary = ScoutEnergyBoundary()
    replay_sha = aggregate_sha256(replay_sha_inputs)
    replay = {
        "artifact_kind": "scout_wearable_provider_live_executor_fixture_replay",
        "artifact_version": "wearable_provider_live_executor_fixture_replay.v1",
        "source_provider": request_plan["source_provider"],
        "source_path": source_path,
        "sha256": replay_sha,
        "request_plan": {
            "artifact_kind": request_plan["artifact_kind"],
            "source_provider": request_plan["source_provider"],
            "source_path": str(request_plan_path),
            "sha256": request_plan["sha256"],
            "query_window": request_plan["query_window"],
            "capabilities": [slot["capability"] for slot in request_plan["request_slots"]],
        },
        "executor_registration": {
            "artifact_kind": executor_registration["artifact_kind"],
            "source_provider": executor_registration["source_provider"],
            "source_path": str(executor_registration_path),
            "sha256": executor_registration["sha256"],
            "executor_kind": executor_registration["executor_registration"]["executor_kind"],
            "executor_ref_exposed": False,
            "executor_ref_sha256": executor_registration["executor_registration"]["executor_ref_sha256"],
            "credential_value_exposed": False,
            "live_provider_credentials_loaded": False,
        },
        "readiness": {
            "artifact_kind": readiness["artifact_kind"],
            "source_provider": readiness["source_provider"],
            "source_path": readiness["source_path"],
            "sha256": readiness["sha256"],
            "ready_for_live_execution": readiness["ready_for_live_execution"],
            "execution_blockers": readiness["execution_blockers"],
        },
        "response_fixture": {
            "source_path": str(response_fixture_path),
            "sha256": response_sha,
            "provider_fixture": _provider_fixture_for_live_provider(request_plan["source_provider"]),
            "raw_response_embedded": False,
            "request_body_exposed": False,
        },
        "transport": {
            "transport_mode": "executor_fixture_replay_only",
            "request_executor_bound": False,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "raw_response_committed": False,
        },
        "data_quality": data_quality.model_dump(mode="json"),
        "privacy": privacy.model_dump(mode="json"),
        "boundary": boundary.model_dump(mode="json"),
        "mutation": {
            "source_file_mutated": False,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "phase1_runtime_mutated": False,
            "safety_api_called": False,
            "raw_payload_committed": False,
            "raw_health_payload_shared": False,
            "raw_track_shared": False,
            "exact_timestamps_shared": False,
        },
    }
    if handoff_package is not None:
        replay["handoff_package"] = {
            "artifact_kind": handoff_package["artifact_kind"],
            "source_provider": handoff_package["source_provider"],
            "source_path": str(handoff_package_path),
            "sha256": handoff_package["sha256"],
            "request_descriptor_count": handoff_package["request_descriptor_count"],
            "ready_for_live_execution": handoff_package["readiness"]["ready_for_live_execution"],
            "execution_blockers": handoff_package["readiness"]["execution_blockers"],
        }
    return replay


def _provider_live_executor_response_manifest_artifact(
    *,
    handoff_package: dict[str, Any],
    handoff_package_path: Path,
    response_payload_path: Path,
    pickup_manifest: dict[str, Any] | None = None,
    pickup_manifest_path: Path | None = None,
) -> dict[str, Any]:
    response_sha = sha256_file(response_payload_path)
    data_quality = ScoutEnergyDataQuality(
        heart_rate_confidence="low",
        gps_confidence="low",
        provider_value_confidence="low",
        limitations=[
            "provider live executor response manifest references a local response payload only",
            "response payload is represented by source path and sha256 but raw payload is not embedded",
            "no network request, provider API call, remote upload, or runtime ingest is performed",
        ],
    )
    privacy = ScoutEnergyPrivacy()
    boundary = ScoutEnergyBoundary()
    manifest_sha = aggregate_sha256(
        [
            handoff_package["sha256"],
            pickup_manifest["sha256"] if pickup_manifest else None,
            response_sha,
            {
                "artifact": "provider_live_executor_response_manifest",
                "transport_mode": "executor_response_manifest_only",
                "pickup_manifest_bound": pickup_manifest is not None,
            },
        ]
    )
    manifest = {
        "artifact_kind": "scout_wearable_provider_live_executor_response_manifest",
        "artifact_version": "wearable_provider_live_executor_response_manifest.v1",
        "source_provider": handoff_package["source_provider"],
        "source_path": (
            f"{pickup_manifest_path}+{response_payload_path}"
            if pickup_manifest_path is not None
            else f"{handoff_package_path}+{response_payload_path}"
        ),
        "sha256": manifest_sha,
        "handoff_package": {
            "artifact_kind": handoff_package["artifact_kind"],
            "source_provider": handoff_package["source_provider"],
            "source_path": str(handoff_package_path),
            "sha256": handoff_package["sha256"],
            "request_descriptor_count": handoff_package["request_descriptor_count"],
            "ready_for_live_execution": handoff_package["readiness"]["ready_for_live_execution"],
            "execution_blockers": handoff_package["readiness"]["execution_blockers"],
        },
        "response_payload": {
            "source_path": str(response_payload_path),
            "sha256": response_sha,
            "provider_fixture": _provider_fixture_for_live_provider(handoff_package["source_provider"]),
            "payload_kind": "local_executor_response_payload_ref",
            "raw_response_embedded": False,
            "raw_response_committed": False,
            "request_body_exposed": False,
            "credential_value_exposed": False,
        },
        "transport": {
            "transport_mode": "executor_response_manifest_only",
            "request_executor_bound": False,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "raw_response_committed": False,
        },
        "data_quality": data_quality.model_dump(mode="json"),
        "privacy": privacy.model_dump(mode="json"),
        "boundary": boundary.model_dump(mode="json"),
        "mutation": {
            "source_file_mutated": False,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "phase1_runtime_mutated": False,
            "safety_api_called": False,
            "raw_payload_committed": False,
            "raw_health_payload_shared": False,
            "raw_track_shared": False,
            "exact_timestamps_shared": False,
        },
    }
    if pickup_manifest is not None and pickup_manifest_path is not None:
        manifest["pickup_manifest"] = {
            "artifact_kind": pickup_manifest["artifact_kind"],
            "source_provider": pickup_manifest["source_provider"],
            "source_path": str(pickup_manifest_path),
            "sha256": pickup_manifest["sha256"],
            "pickup_status": pickup_manifest["pickup"]["pickup_status"],
            "external_execution_authorized": pickup_manifest["pickup"][
                "external_execution_authorized"
            ],
            "network_execution_disabled_by_local_contract": pickup_manifest["pickup"][
                "network_execution_disabled_by_local_contract"
            ],
        }
    return manifest


def _executor_response_inbox_index_entry(path: Path) -> dict[str, Any]:
    file_sha = sha256_file(path)
    base_entry: dict[str, Any] = {
        "source_path": str(path),
        "file_sha256": file_sha,
        "artifact_kind": None,
        "source_provider": None,
        "manifest_sha256": None,
        "handoff_package_sha256": None,
        "response_payload_sha256": None,
        "handoff_ref_valid": False,
        "response_payload_ref_valid": False,
        "eligible_for_consumption_precheck": False,
        "rejection_reason": None,
    }
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        base_entry["rejection_reason"] = "invalid_json"
        return base_entry
    base_entry["artifact_kind"] = manifest.get("artifact_kind")
    base_entry["source_provider"] = manifest.get("source_provider")
    base_entry["manifest_sha256"] = manifest.get("sha256")
    if manifest.get("artifact_kind") != "scout_wearable_provider_live_executor_response_manifest":
        base_entry["rejection_reason"] = "not_executor_response_manifest"
        return base_entry
    try:
        _assert_executor_response_manifest_artifact_safe(manifest)
        handoff_path = Path(manifest["handoff_package"]["source_path"])
        handoff_package = _load_executor_handoff_package_artifact(handoff_path)
        _assert_executor_handoff_package_artifact_safe(handoff_package)
        if handoff_package["sha256"] != manifest["handoff_package"]["sha256"]:
            raise ValueError("handoff sha256 mismatch")
        response_payload_path = Path(manifest["response_payload"]["source_path"])
        if sha256_file(response_payload_path) != manifest["response_payload"]["sha256"]:
            raise ValueError("response payload sha256 mismatch")
    except (KeyError, OSError, ValueError) as exc:
        base_entry["handoff_package_sha256"] = manifest.get("handoff_package", {}).get("sha256")
        base_entry["response_payload_sha256"] = manifest.get("response_payload", {}).get("sha256")
        base_entry["rejection_reason"] = str(exc)
        return base_entry
    base_entry.update(
        {
            "handoff_package_sha256": manifest["handoff_package"]["sha256"],
            "response_payload_sha256": manifest["response_payload"]["sha256"],
            "handoff_ref_valid": True,
            "response_payload_ref_valid": True,
            "eligible_for_consumption_precheck": True,
            "rejection_reason": None,
        }
    )
    return base_entry


def _executor_handoff_outbox_index_entry(path: Path) -> dict[str, Any]:
    file_sha = sha256_file(path)
    base_entry: dict[str, Any] = {
        "source_path": str(path),
        "file_sha256": file_sha,
        "artifact_kind": None,
        "source_provider": None,
        "handoff_package_sha256": None,
        "request_plan_sha256": None,
        "executor_registration_sha256": None,
        "request_plan_ref_valid": False,
        "executor_registration_ref_valid": False,
        "request_descriptor_count": None,
        "ready_for_live_execution": None,
        "execution_blockers": [],
        "eligible_for_executor_pickup_precheck": False,
        "rejection_reason": None,
    }
    try:
        handoff = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        base_entry["rejection_reason"] = "invalid_json"
        return base_entry
    base_entry["artifact_kind"] = handoff.get("artifact_kind")
    base_entry["source_provider"] = handoff.get("source_provider")
    base_entry["handoff_package_sha256"] = handoff.get("sha256")
    if handoff.get("artifact_kind") != "scout_wearable_provider_live_executor_handoff_package":
        base_entry["rejection_reason"] = "not_executor_handoff_package"
        return base_entry
    try:
        _assert_executor_handoff_package_artifact_safe(handoff)
        request_plan_path = Path(handoff["request_plan"]["source_path"])
        executor_registration_path = Path(handoff["executor_registration"]["source_path"])
        request_plan = _load_request_plan_artifact(request_plan_path)
        _assert_request_plan_artifact_safe(request_plan)
        executor_registration = _load_executor_registration_artifact(executor_registration_path)
        _assert_executor_registration_artifact_safe(executor_registration)
        _assert_executor_registration_matches_request_plan(
            executor_registration,
            request_plan=request_plan,
        )
        readiness = _provider_live_executor_readiness_artifact(
            request_plan=request_plan,
            request_plan_path=request_plan_path,
            executor_registration=executor_registration,
            executor_registration_path=executor_registration_path,
        )
        _assert_executor_handoff_package_matches_sources(
            handoff,
            handoff_package_path=path,
            request_plan=request_plan,
            request_plan_path=request_plan_path,
            executor_registration=executor_registration,
            executor_registration_path=executor_registration_path,
            readiness=readiness,
        )
    except (KeyError, OSError, ValueError) as exc:
        base_entry["request_plan_sha256"] = handoff.get("request_plan", {}).get("sha256")
        base_entry["executor_registration_sha256"] = handoff.get("executor_registration", {}).get("sha256")
        base_entry["request_descriptor_count"] = handoff.get("request_descriptor_count")
        base_entry["ready_for_live_execution"] = handoff.get("readiness", {}).get("ready_for_live_execution")
        base_entry["execution_blockers"] = handoff.get("readiness", {}).get("execution_blockers", [])
        base_entry["rejection_reason"] = str(exc)
        return base_entry
    base_entry.update(
        {
            "request_plan_sha256": handoff["request_plan"]["sha256"],
            "executor_registration_sha256": handoff["executor_registration"]["sha256"],
            "request_plan_ref_valid": True,
            "executor_registration_ref_valid": True,
            "request_descriptor_count": handoff["request_descriptor_count"],
            "ready_for_live_execution": handoff["readiness"]["ready_for_live_execution"],
            "execution_blockers": handoff["readiness"]["execution_blockers"],
            "eligible_for_executor_pickup_precheck": True,
            "rejection_reason": None,
        }
    )
    return base_entry


def _provider_live_executor_handoff_pickup_manifest_artifact(
    *,
    outbox_index: dict[str, Any],
    outbox_index_path: Path,
    selected_entry: dict[str, Any],
    handoff_package: dict[str, Any],
) -> dict[str, Any]:
    data_quality = ScoutEnergyDataQuality(
        heart_rate_confidence="low",
        gps_confidence="low",
        provider_value_confidence="low",
        limitations=[
            "executor handoff pickup manifest is local external-executor review evidence only",
            "selected handoff package file sha256 is rechecked before pickup manifest creation",
            "network execution remains disabled by local contract",
            "no network request, provider API call, remote upload, or runtime ingest is performed",
        ],
    )
    privacy = ScoutEnergyPrivacy()
    boundary = ScoutEnergyBoundary()
    pickup_sha = aggregate_sha256(
        [
            outbox_index["sha256"],
            selected_entry["file_sha256"],
            handoff_package["sha256"],
            {
                "artifact": "provider_live_executor_handoff_pickup_manifest",
                "transport_mode": "executor_handoff_pickup_manifest_only",
            },
        ]
    )
    return {
        "artifact_kind": "scout_wearable_provider_live_executor_handoff_pickup_manifest",
        "artifact_version": "wearable_provider_live_executor_handoff_pickup_manifest.v1",
        "source_provider": handoff_package["source_provider"],
        "source_path": selected_entry["source_path"],
        "sha256": pickup_sha,
        "outbox_index": {
            "artifact_kind": outbox_index["artifact_kind"],
            "source_provider": outbox_index["source_provider"],
            "source_path": str(outbox_index_path),
            "sha256": outbox_index["sha256"],
            "eligible_handoff_count": outbox_index["outbox"]["eligible_handoff_count"],
        },
        "selected_handoff": {
            "artifact_kind": handoff_package["artifact_kind"],
            "source_provider": handoff_package["source_provider"],
            "source_path": selected_entry["source_path"],
            "file_sha256": selected_entry["file_sha256"],
            "sha256": handoff_package["sha256"],
            "request_plan_sha256": selected_entry["request_plan_sha256"],
            "executor_registration_sha256": selected_entry["executor_registration_sha256"],
            "request_descriptor_count": selected_entry["request_descriptor_count"],
            "ready_for_live_execution": selected_entry["ready_for_live_execution"],
            "execution_blockers": selected_entry["execution_blockers"],
            "eligible_for_executor_pickup_precheck": selected_entry[
                "eligible_for_executor_pickup_precheck"
            ],
        },
        "pickup": {
            "pickup_status": "ready_for_external_executor_review",
            "external_execution_authorized": False,
            "request_executor_bound": False,
            "network_execution_disabled_by_local_contract": True,
            "requires_separate_account_authorized_executor": True,
            "handoff_file_mutated": False,
            "outbox_file_mutated": False,
            "outbox_file_moved": False,
            "outbox_file_deleted": False,
        },
        "transport": {
            "transport_mode": "executor_handoff_pickup_manifest_only",
            "request_executor_bound": False,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "raw_response_committed": False,
        },
        "data_quality": data_quality.model_dump(mode="json"),
        "privacy": privacy.model_dump(mode="json"),
        "boundary": boundary.model_dump(mode="json"),
        "mutation": {
            "source_file_mutated": False,
            "outbox_file_mutated": False,
            "outbox_file_moved": False,
            "outbox_file_deleted": False,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "phase1_runtime_mutated": False,
            "safety_api_called": False,
            "raw_payload_committed": False,
            "raw_health_payload_shared": False,
            "raw_track_shared": False,
            "exact_timestamps_shared": False,
        },
    }


def _provider_live_transport_response_admission_artifact(
    *,
    request_plan: dict[str, Any],
    request_plan_path: Path,
    response_fixture_path: Path,
    provider_fixture: ProviderApiFixture,
    admitted_capabilities: list[str],
    sanitized_result: dict[str, Any],
) -> dict[str, Any]:
    response_sha = sha256_file(response_fixture_path)
    data_quality = ScoutEnergyDataQuality(
        heart_rate_confidence=sanitized_result["data_quality"]["heart_rate_confidence"],
        gps_confidence=sanitized_result["data_quality"]["gps_confidence"],
        missing_hr_seconds=sanitized_result["data_quality"].get("missing_hr_seconds", 0),
        missing_hr_intervals=sanitized_result["data_quality"].get("missing_hr_intervals", []),
        sample_cadence_s=sanitized_result["data_quality"].get("sample_cadence_s"),
        provider_value_confidence=sanitized_result["data_quality"]["provider_value_confidence"],
        limitations=[
            "provider live response admission uses a local response fixture only",
            "response fixture is sanitized through the provider API fixture importer",
            "no live provider API call, network request, or runtime ingest is performed",
        ],
    )
    privacy = ScoutEnergyPrivacy()
    boundary = ScoutEnergyBoundary()
    admission_sha = aggregate_sha256(
        [
            request_plan["sha256"],
            response_sha,
            {
                "admitted_capabilities": admitted_capabilities,
                "sanitized_import_paths": sanitized_result["sanitized_import_paths"],
                "transport_mode": "response_fixture_admission_only",
            },
        ]
    )
    return {
        "artifact_kind": "scout_wearable_provider_live_transport_response_admission",
        "artifact_version": "wearable_provider_live_transport_response_admission.v1",
        "source_provider": request_plan["source_provider"],
        "source_path": f"{request_plan_path}+{response_fixture_path}",
        "sha256": admission_sha,
        "request_plan": {
            "artifact_kind": request_plan["artifact_kind"],
            "source_provider": request_plan["source_provider"],
            "source_path": str(request_plan_path),
            "sha256": request_plan["sha256"],
            "query_window": request_plan["query_window"],
        },
        "response_fixture": {
            "source_path": str(response_fixture_path),
            "sha256": response_sha,
            "provider_fixture": provider_fixture,
            "raw_response_embedded": False,
            "request_body_exposed": False,
        },
        "admitted_capabilities": admitted_capabilities,
        "sanitized_import_result": sanitized_result,
        "transport": {
            "transport_mode": "response_fixture_admission_only",
            "request_executor_bound": False,
            "network_request_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "raw_response_committed": False,
        },
        "data_quality": data_quality.model_dump(mode="json"),
        "privacy": privacy.model_dump(mode="json"),
        "boundary": boundary.model_dump(mode="json"),
        "mutation": {
            "sanitized_imports_written": True,
            "source_file_mutated": False,
            "network_request_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "phase1_runtime_mutated": False,
            "safety_api_called": False,
            "raw_payload_committed": False,
            "raw_health_payload_shared": False,
            "raw_track_shared": False,
            "exact_timestamps_shared": False,
        },
    }


def _provider_live_transport_materialization_artifact(
    *,
    admission: dict[str, Any],
    admission_path: Path,
    normalization: dict[str, Any],
) -> dict[str, Any]:
    data_quality = ScoutEnergyDataQuality(
        heart_rate_confidence=normalization["data_quality"]["heart_rate_confidence"],
        gps_confidence=normalization["data_quality"]["gps_confidence"],
        missing_hr_seconds=normalization["data_quality"].get("missing_hr_seconds", 0),
        missing_hr_intervals=normalization["data_quality"].get("missing_hr_intervals", []),
        sample_cadence_s=normalization["data_quality"].get("sample_cadence_s"),
        provider_value_confidence=normalization["data_quality"]["provider_value_confidence"],
        limitations=[
            "provider live materialization normalizes admitted sanitized imports only",
            "normalized activity summaries are local artifacts and not runtime ingest",
            "no live provider API call, network request, or Phase 1 mutation is performed",
        ],
    )
    privacy = ScoutEnergyPrivacy()
    boundary = ScoutEnergyBoundary()
    materialization_sha = aggregate_sha256(
        [
            admission["sha256"],
            normalization["sha256"],
            {
                "normalized_paths": normalization["normalized_paths"],
                "transport_mode": "materialization_only",
            },
        ]
    )
    return {
        "artifact_kind": "scout_wearable_provider_live_transport_materialization",
        "artifact_version": "wearable_provider_live_transport_materialization.v1",
        "source_provider": admission["source_provider"],
        "source_path": str(admission_path),
        "sha256": materialization_sha,
        "admission": {
            "artifact_kind": admission["artifact_kind"],
            "source_provider": admission["source_provider"],
            "source_path": str(admission_path),
            "sha256": admission["sha256"],
        },
        "normalization": normalization,
        "transport": {
            "transport_mode": "materialization_only",
            "request_executor_bound": False,
            "network_request_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "raw_response_committed": False,
        },
        "data_quality": data_quality.model_dump(mode="json"),
        "privacy": privacy.model_dump(mode="json"),
        "boundary": boundary.model_dump(mode="json"),
        "mutation": {
            "normalized_summaries_written": True,
            "source_file_mutated": False,
            "network_request_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "phase1_runtime_mutated": False,
            "safety_api_called": False,
            "raw_payload_committed": False,
            "raw_health_payload_shared": False,
            "raw_track_shared": False,
            "exact_timestamps_shared": False,
        },
    }


def _provider_live_transport_sync_package_artifact(
    *,
    materialization: dict[str, Any],
    materialization_path: Path,
    normalized_summaries: list[dict[str, Any]],
) -> dict[str, Any]:
    data_quality = ScoutEnergyDataQuality(
        heart_rate_confidence=materialization["data_quality"]["heart_rate_confidence"],
        gps_confidence=materialization["data_quality"]["gps_confidence"],
        missing_hr_seconds=materialization["data_quality"].get("missing_hr_seconds", 0),
        missing_hr_intervals=materialization["data_quality"].get("missing_hr_intervals", []),
        sample_cadence_s=materialization["data_quality"].get("sample_cadence_s"),
        provider_value_confidence=materialization["data_quality"]["provider_value_confidence"],
        limitations=sorted(
            {
                *materialization["data_quality"].get("limitations", []),
                "provider live sync package references validated local summaries only",
                "no remote upload, network sync, live provider call, or runtime ingest is performed",
            }
        ),
    )
    privacy = ScoutEnergyPrivacy()
    boundary = ScoutEnergyBoundary()
    package_sha = aggregate_sha256(
        [
            materialization["sha256"],
            [
                {
                    "source_path": summary["source_path"],
                    "sha256": summary["sha256"],
                    "activity_id": summary["activity_id"],
                    "valid": summary["valid"],
                }
                for summary in normalized_summaries
            ],
            {
                "transport_mode": "local_sync_package_only",
                "remote_upload_allowed": False,
            },
        ]
    )
    return {
        "artifact_kind": "scout_wearable_provider_live_transport_sync_package",
        "artifact_version": "wearable_provider_live_transport_sync_package.v1",
        "source_provider": materialization["source_provider"],
        "source_path": str(materialization_path),
        "sha256": package_sha,
        "materialization": {
            "artifact_kind": materialization["artifact_kind"],
            "source_provider": materialization["source_provider"],
            "source_path": str(materialization_path),
            "sha256": materialization["sha256"],
        },
        "normalized_summary_count": len(normalized_summaries),
        "normalized_summaries": normalized_summaries,
        "transport": {
            "transport_mode": "local_sync_package_only",
            "request_executor_bound": False,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "raw_response_committed": False,
        },
        "data_quality": data_quality.model_dump(mode="json"),
        "privacy": privacy.model_dump(mode="json"),
        "boundary": boundary.model_dump(mode="json"),
        "mutation": {
            "source_file_mutated": False,
            "network_request_performed": False,
            "network_sync_performed": False,
            "remote_upload_allowed": False,
            "remote_upload_performed": False,
            "real_provider_api_called": False,
            "runtime_ingest_performed": False,
            "phase1_runtime_mutated": False,
            "safety_api_called": False,
            "raw_payload_committed": False,
            "raw_health_payload_shared": False,
            "raw_track_shared": False,
            "exact_timestamps_shared": False,
        },
    }


def _load_preflight_artifact(preflight_path: Path) -> dict[str, Any]:
    payload = json.loads(preflight_path.read_text(encoding="utf-8"))
    if payload.get("artifact_kind") != "scout_wearable_provider_live_transport_preflight":
        raise ValueError("provider live transport request plan requires a preflight artifact")
    return payload


def _load_request_plan_artifact(request_plan_path: Path) -> dict[str, Any]:
    payload = json.loads(request_plan_path.read_text(encoding="utf-8"))
    if payload.get("artifact_kind") != "scout_wearable_provider_live_transport_request_plan":
        raise ValueError("provider live response admission requires a request-plan artifact")
    return payload


def _load_response_admission_artifact(admission_path: Path) -> dict[str, Any]:
    payload = json.loads(admission_path.read_text(encoding="utf-8"))
    if payload.get("artifact_kind") != "scout_wearable_provider_live_transport_response_admission":
        raise ValueError("provider live materialization requires a response-admission artifact")
    return payload


def _load_materialization_artifact(materialization_path: Path) -> dict[str, Any]:
    payload = json.loads(materialization_path.read_text(encoding="utf-8"))
    if payload.get("artifact_kind") != "scout_wearable_provider_live_transport_materialization":
        raise ValueError("provider live sync package requires a materialization artifact")
    return payload


def _load_executor_registration_artifact(executor_registration_path: Path) -> dict[str, Any]:
    payload = json.loads(executor_registration_path.read_text(encoding="utf-8"))
    if payload.get("artifact_kind") != "scout_wearable_provider_live_executor_registration":
        raise ValueError("provider live executor readiness requires an executor-registration artifact")
    return payload


def _load_executor_handoff_package_artifact(handoff_package_path: Path) -> dict[str, Any]:
    payload = json.loads(handoff_package_path.read_text(encoding="utf-8"))
    if payload.get("artifact_kind") != "scout_wearable_provider_live_executor_handoff_package":
        raise ValueError("provider live handoff fixture replay requires an executor handoff package")
    return payload


def _load_executor_handoff_outbox_index(outbox_index_path: Path) -> dict[str, Any]:
    payload = json.loads(outbox_index_path.read_text(encoding="utf-8"))
    if payload.get("artifact_kind") != "scout_wearable_provider_live_executor_handoff_outbox_index":
        raise ValueError("provider live handoff pickup requires an outbox-index artifact")
    return payload


def _load_executor_handoff_pickup_manifest_artifact(pickup_manifest_path: Path) -> dict[str, Any]:
    payload = json.loads(pickup_manifest_path.read_text(encoding="utf-8"))
    if payload.get("artifact_kind") != "scout_wearable_provider_live_executor_handoff_pickup_manifest":
        raise ValueError("provider live pickup response manifest requires a handoff pickup manifest")
    return payload


def _load_executor_response_manifest_artifact(executor_response_manifest_path: Path) -> dict[str, Any]:
    payload = json.loads(executor_response_manifest_path.read_text(encoding="utf-8"))
    if payload.get("artifact_kind") != "scout_wearable_provider_live_executor_response_manifest":
        raise ValueError("provider live executor response admission requires an executor response manifest")
    return payload


def _load_executor_fixture_replay_artifact(fixture_replay_path: Path) -> dict[str, Any]:
    payload = json.loads(fixture_replay_path.read_text(encoding="utf-8"))
    if payload.get("artifact_kind") != "scout_wearable_provider_live_executor_fixture_replay":
        raise ValueError("provider live replay admission requires an executor fixture-replay artifact")
    return payload


def _assert_preflight_artifact_safe(preflight: dict[str, Any]) -> None:
    authorization = preflight.get("authorization", {})
    if not authorization.get("explicit_consent") or not authorization.get("account_authorized"):
        raise ValueError("provider live transport request plan requires authorized explicit-consent preflight")
    if authorization.get("token_value_exposed"):
        raise ValueError("provider live transport request plan cannot use exposed token values")
    if not preflight.get("capability_review", {}).get("capability_flags_valid"):
        raise ValueError("provider live transport request plan requires valid preflight capability flags")
    transport = preflight.get("transport", {})
    if (
        transport.get("network_request_performed")
        or transport.get("real_provider_api_called")
        or transport.get("runtime_ingest_performed")
    ):
        raise ValueError("provider live transport request plan requires preflight-only transport")
    privacy = preflight.get("privacy", {})
    if privacy.get("raw_health_payload_shared") or privacy.get("raw_track_shared") or privacy.get("exact_timestamps_shared"):
        raise ValueError("provider live transport request plan requires sanitized preflight privacy")
    boundary = preflight.get("boundary", {})
    if boundary.get("medical_diagnosis") or boundary.get("phase1_runtime_safety_truth"):
        raise ValueError("provider live transport request plan cannot use medical or Phase 1 safety truth preflight")


def _assert_request_plan_artifact_safe(request_plan: dict[str, Any]) -> None:
    transport = request_plan.get("transport", {})
    if (
        transport.get("request_executor_bound")
        or transport.get("network_request_performed")
        or transport.get("real_provider_api_called")
        or transport.get("runtime_ingest_performed")
    ):
        raise ValueError("provider live response admission requires request-plan-only transport")
    privacy = request_plan.get("privacy", {})
    if privacy.get("raw_health_payload_shared") or privacy.get("raw_track_shared") or privacy.get("exact_timestamps_shared"):
        raise ValueError("provider live response admission requires sanitized request-plan privacy")
    boundary = request_plan.get("boundary", {})
    if boundary.get("medical_diagnosis") or boundary.get("phase1_runtime_safety_truth"):
        raise ValueError("provider live response admission cannot use medical or Phase 1 safety truth request plan")


def _assert_response_admission_artifact_safe(admission: dict[str, Any]) -> None:
    transport = admission.get("transport", {})
    if (
        transport.get("request_executor_bound")
        or transport.get("network_request_performed")
        or transport.get("real_provider_api_called")
        or transport.get("runtime_ingest_performed")
    ):
        raise ValueError("provider live materialization requires response-fixture admission only")
    privacy = admission.get("privacy", {})
    if privacy.get("raw_health_payload_shared") or privacy.get("raw_track_shared") or privacy.get("exact_timestamps_shared"):
        raise ValueError("provider live materialization requires sanitized response-admission privacy")
    boundary = admission.get("boundary", {})
    if boundary.get("medical_diagnosis") or boundary.get("phase1_runtime_safety_truth"):
        raise ValueError("provider live materialization cannot use medical or Phase 1 safety truth admission")


def _assert_materialization_artifact_safe(materialization: dict[str, Any]) -> None:
    transport = materialization.get("transport", {})
    if (
        transport.get("request_executor_bound")
        or transport.get("network_request_performed")
        or transport.get("real_provider_api_called")
        or transport.get("runtime_ingest_performed")
    ):
        raise ValueError("provider live sync package requires materialization-only transport")
    if transport.get("network_sync_performed") or transport.get("remote_upload_performed"):
        raise ValueError("provider live sync package cannot use already synced materialization")
    privacy = materialization.get("privacy", {})
    if privacy.get("raw_health_payload_shared") or privacy.get("raw_track_shared") or privacy.get("exact_timestamps_shared"):
        raise ValueError("provider live sync package requires sanitized materialization privacy")
    boundary = materialization.get("boundary", {})
    if boundary.get("medical_diagnosis") or boundary.get("phase1_runtime_safety_truth"):
        raise ValueError("provider live sync package cannot use medical or Phase 1 safety truth materialization")


def _assert_executor_registration_artifact_safe(registration: dict[str, Any]) -> None:
    executor_registration = registration.get("executor_registration", {})
    if not executor_registration.get("executor_registered"):
        raise ValueError("provider live executor readiness requires registered executor metadata")
    if executor_registration.get("executor_ref_exposed") or executor_registration.get("credential_value_exposed"):
        raise ValueError("provider live executor readiness cannot use exposed executor refs or credentials")
    if executor_registration.get("live_provider_credentials_loaded"):
        raise ValueError("provider live executor readiness cannot use loaded live provider credentials")
    transport = registration.get("transport", {})
    if (
        transport.get("request_executor_bound")
        or transport.get("network_request_performed")
        or transport.get("network_sync_performed")
        or transport.get("remote_upload_allowed")
        or transport.get("remote_upload_performed")
        or transport.get("real_provider_api_called")
        or transport.get("runtime_ingest_performed")
    ):
        raise ValueError("provider live executor readiness requires registration-only transport")
    privacy = registration.get("privacy", {})
    if privacy.get("raw_health_payload_shared") or privacy.get("raw_track_shared") or privacy.get("exact_timestamps_shared"):
        raise ValueError("provider live executor readiness requires sanitized executor registration privacy")
    boundary = registration.get("boundary", {})
    if boundary.get("medical_diagnosis") or boundary.get("phase1_runtime_safety_truth"):
        raise ValueError("provider live executor readiness cannot use medical or Phase 1 safety truth registration")


def _assert_executor_registration_matches_request_plan(
    registration: dict[str, Any],
    *,
    request_plan: dict[str, Any],
) -> None:
    if registration["source_provider"] != request_plan["source_provider"]:
        raise ValueError("executor registration provider does not match request plan provider")
    supported = set(registration["executor_registration"]["supported_capabilities"])
    requested = {slot["capability"] for slot in request_plan["request_slots"]}
    unsupported = sorted(requested - supported)
    if unsupported:
        raise ValueError(
            "executor registration does not support request-plan capabilities: "
            + ", ".join(unsupported)
        )


def _assert_executor_handoff_package_artifact_safe(handoff_package: dict[str, Any]) -> None:
    request_plan = handoff_package.get("request_plan", {})
    executor_registration = handoff_package.get("executor_registration", {})
    if not request_plan.get("source_path") or not request_plan.get("sha256"):
        raise ValueError("provider live handoff fixture replay requires request-plan source metadata")
    if not executor_registration.get("source_path") or not executor_registration.get("sha256"):
        raise ValueError("provider live handoff fixture replay requires executor-registration source metadata")
    if executor_registration.get("executor_ref_exposed") or executor_registration.get("credential_value_exposed"):
        raise ValueError("provider live handoff fixture replay cannot use exposed executor refs or credentials")
    if executor_registration.get("live_provider_credentials_loaded"):
        raise ValueError("provider live handoff fixture replay cannot use loaded live provider credentials")
    readiness = handoff_package.get("readiness", {})
    if readiness.get("ready_for_live_execution"):
        raise ValueError("provider live handoff fixture replay cannot use live execution readiness")
    for descriptor in handoff_package.get("request_descriptors", []):
        if descriptor.get("request_body_exposed") or descriptor.get("raw_response_committed"):
            raise ValueError("provider live handoff fixture replay requires sanitized request descriptors")
    transport = handoff_package.get("transport", {})
    if (
        transport.get("transport_mode") != "executor_handoff_package_only"
        or transport.get("request_executor_bound")
        or transport.get("network_request_performed")
        or transport.get("network_sync_performed")
        or transport.get("remote_upload_allowed")
        or transport.get("remote_upload_performed")
        or transport.get("real_provider_api_called")
        or transport.get("runtime_ingest_performed")
    ):
        raise ValueError("provider live handoff fixture replay requires handoff-package-only transport")
    privacy = handoff_package.get("privacy", {})
    if privacy.get("raw_health_payload_shared") or privacy.get("raw_track_shared") or privacy.get("exact_timestamps_shared"):
        raise ValueError("provider live handoff fixture replay requires sanitized handoff privacy")
    boundary = handoff_package.get("boundary", {})
    if boundary.get("medical_diagnosis") or boundary.get("phase1_runtime_safety_truth"):
        raise ValueError("provider live handoff fixture replay cannot use medical or Phase 1 safety truth handoff")


def _assert_executor_handoff_outbox_index_safe(outbox_index: dict[str, Any]) -> None:
    transport = outbox_index.get("transport", {})
    if (
        transport.get("transport_mode") != "executor_handoff_outbox_index_only"
        or transport.get("request_executor_bound")
        or transport.get("network_request_performed")
        or transport.get("network_sync_performed")
        or transport.get("remote_upload_allowed")
        or transport.get("remote_upload_performed")
        or transport.get("real_provider_api_called")
        or transport.get("runtime_ingest_performed")
    ):
        raise ValueError("provider live handoff pickup requires local-only outbox index transport")
    privacy = outbox_index.get("privacy", {})
    if privacy.get("raw_health_payload_shared") or privacy.get("raw_track_shared") or privacy.get("exact_timestamps_shared"):
        raise ValueError("provider live handoff pickup requires sanitized outbox index privacy")
    boundary = outbox_index.get("boundary", {})
    if boundary.get("medical_diagnosis") or boundary.get("phase1_runtime_safety_truth"):
        raise ValueError("provider live handoff pickup cannot use medical or Phase 1 safety truth outbox index")


def _assert_executor_handoff_pickup_manifest_artifact_safe(pickup_manifest: dict[str, Any]) -> None:
    selected_handoff = pickup_manifest.get("selected_handoff", {})
    if (
        selected_handoff.get("artifact_kind")
        != "scout_wearable_provider_live_executor_handoff_package"
    ):
        raise ValueError("provider live pickup response manifest requires selected handoff metadata")
    if (
        not selected_handoff.get("source_path")
        or not selected_handoff.get("file_sha256")
        or not selected_handoff.get("sha256")
    ):
        raise ValueError("provider live pickup response manifest requires selected handoff refs")
    pickup = pickup_manifest.get("pickup", {})
    if pickup.get("pickup_status") != "ready_for_external_executor_review":
        raise ValueError("provider live pickup response manifest requires review-ready pickup status")
    if pickup.get("external_execution_authorized"):
        raise ValueError("provider live pickup response manifest cannot authorize external execution")
    if not pickup.get("network_execution_disabled_by_local_contract"):
        raise ValueError("provider live pickup response manifest requires disabled network execution")
    if pickup.get("request_executor_bound"):
        raise ValueError("provider live pickup response manifest cannot bind a request executor")
    transport = pickup_manifest.get("transport", {})
    if (
        transport.get("transport_mode") != "executor_handoff_pickup_manifest_only"
        or transport.get("request_executor_bound")
        or transport.get("network_request_performed")
        or transport.get("network_sync_performed")
        or transport.get("remote_upload_allowed")
        or transport.get("remote_upload_performed")
        or transport.get("real_provider_api_called")
        or transport.get("runtime_ingest_performed")
    ):
        raise ValueError("provider live pickup response manifest requires local-only pickup transport")
    privacy = pickup_manifest.get("privacy", {})
    if privacy.get("raw_health_payload_shared") or privacy.get("raw_track_shared") or privacy.get("exact_timestamps_shared"):
        raise ValueError("provider live pickup response manifest requires sanitized pickup privacy")
    boundary = pickup_manifest.get("boundary", {})
    if boundary.get("medical_diagnosis") or boundary.get("phase1_runtime_safety_truth"):
        raise ValueError("provider live pickup response manifest cannot use medical or Phase 1 safety truth pickup")


def _select_executor_handoff_outbox_entry(
    outbox_index: dict[str, Any],
    *,
    handoff_source_path: Path | None,
) -> dict[str, Any]:
    entries = _eligible_executor_handoff_outbox_entries(outbox_index)
    if handoff_source_path is not None:
        handoff_source = str(handoff_source_path)
        entries = [
            entry for entry in entries if entry.get("source_path") == handoff_source
        ]
        if not entries:
            raise ValueError("requested executor handoff package is not eligible in outbox index")
    if not entries:
        raise ValueError("executor handoff outbox index has no eligible handoff package to pick up")
    return entries[0]


def _eligible_executor_handoff_outbox_entries(outbox_index: dict[str, Any]) -> list[dict[str, Any]]:
    return sorted(
        [
            entry
            for entry in outbox_index.get("handoff_packages", [])
            if entry.get("eligible_for_executor_pickup_precheck") is True
        ],
        key=lambda entry: entry["source_path"],
    )


def _assert_executor_handoff_package_matches_sources(
    handoff_package: dict[str, Any],
    *,
    handoff_package_path: Path,
    request_plan: dict[str, Any],
    request_plan_path: Path,
    executor_registration: dict[str, Any],
    executor_registration_path: Path,
    readiness: dict[str, Any],
) -> None:
    if handoff_package["source_provider"] != request_plan["source_provider"]:
        raise ValueError("executor handoff package provider does not match request plan")
    if handoff_package["source_provider"] != executor_registration["source_provider"]:
        raise ValueError("executor handoff package provider does not match executor registration")
    if handoff_package["request_plan"]["sha256"] != request_plan["sha256"]:
        raise ValueError("executor handoff package request-plan sha256 mismatch")
    if handoff_package["executor_registration"]["sha256"] != executor_registration["sha256"]:
        raise ValueError("executor handoff package executor-registration sha256 mismatch")
    expected_handoff = _provider_live_executor_handoff_package_artifact(
        request_plan=request_plan,
        request_plan_path=request_plan_path,
        executor_registration=executor_registration,
        executor_registration_path=executor_registration_path,
        readiness=readiness,
    )
    if handoff_package["sha256"] != expected_handoff["sha256"]:
        raise ValueError("executor handoff package sha256 does not match local sources")
    if handoff_package["request_descriptor_count"] != expected_handoff["request_descriptor_count"]:
        raise ValueError("executor handoff package request descriptor count mismatch")
    if str(handoff_package_path) == handoff_package["request_plan"]["source_path"]:
        raise ValueError("executor handoff package cannot point request plan at itself")


def _assert_executor_response_manifest_artifact_safe(manifest: dict[str, Any]) -> None:
    handoff_package = manifest.get("handoff_package", {})
    if not handoff_package.get("source_path") or not handoff_package.get("sha256"):
        raise ValueError("provider live executor response admission requires handoff package metadata")
    if handoff_package.get("ready_for_live_execution"):
        raise ValueError("provider live executor response admission cannot use live execution readiness")
    response_payload = manifest.get("response_payload", {})
    if not response_payload.get("source_path") or not response_payload.get("sha256"):
        raise ValueError("provider live executor response admission requires response payload metadata")
    if (
        response_payload.get("raw_response_embedded")
        or response_payload.get("raw_response_committed")
        or response_payload.get("request_body_exposed")
        or response_payload.get("credential_value_exposed")
    ):
        raise ValueError("provider live executor response admission requires sanitized response manifest")
    transport = manifest.get("transport", {})
    if (
        transport.get("transport_mode") != "executor_response_manifest_only"
        or transport.get("request_executor_bound")
        or transport.get("network_request_performed")
        or transport.get("network_sync_performed")
        or transport.get("remote_upload_allowed")
        or transport.get("remote_upload_performed")
        or transport.get("real_provider_api_called")
        or transport.get("runtime_ingest_performed")
    ):
        raise ValueError("provider live executor response admission requires response-manifest-only transport")
    privacy = manifest.get("privacy", {})
    if privacy.get("raw_health_payload_shared") or privacy.get("raw_track_shared") or privacy.get("exact_timestamps_shared"):
        raise ValueError("provider live executor response admission requires sanitized response manifest privacy")
    boundary = manifest.get("boundary", {})
    if boundary.get("medical_diagnosis") or boundary.get("phase1_runtime_safety_truth"):
        raise ValueError("provider live executor response admission cannot use medical or Phase 1 safety truth manifest")


def _assert_executor_fixture_replay_artifact_safe(fixture_replay: dict[str, Any]) -> None:
    response_fixture = fixture_replay.get("response_fixture", {})
    if response_fixture.get("raw_response_embedded") or response_fixture.get("request_body_exposed"):
        raise ValueError("provider live replay admission requires sanitized response fixture replay")
    readiness = fixture_replay.get("readiness", {})
    if readiness.get("ready_for_live_execution"):
        raise ValueError("provider live replay admission cannot use live execution readiness")
    transport = fixture_replay.get("transport", {})
    if (
        transport.get("request_executor_bound")
        or transport.get("network_request_performed")
        or transport.get("network_sync_performed")
        or transport.get("remote_upload_allowed")
        or transport.get("remote_upload_performed")
        or transport.get("real_provider_api_called")
        or transport.get("runtime_ingest_performed")
    ):
        raise ValueError("provider live replay admission requires fixture-replay-only transport")
    privacy = fixture_replay.get("privacy", {})
    if privacy.get("raw_health_payload_shared") or privacy.get("raw_track_shared") or privacy.get("exact_timestamps_shared"):
        raise ValueError("provider live replay admission requires sanitized fixture replay privacy")
    boundary = fixture_replay.get("boundary", {})
    if boundary.get("medical_diagnosis") or boundary.get("phase1_runtime_safety_truth"):
        raise ValueError("provider live replay admission cannot use medical or Phase 1 safety truth fixture replay")


def _executor_registration_summary(
    registration: dict[str, Any] | None,
    *,
    executor_registration_path: Path | None,
) -> dict[str, Any]:
    if registration is None:
        return {
            "executor_registered": False,
            "executor_registration_path": None,
            "executor_kind": None,
            "executor_ref_exposed": False,
            "executor_ref_sha256": None,
            "supported_capabilities": [],
            "credential_value_exposed": False,
            "network_execution_enabled": False,
            "live_provider_credentials_loaded": False,
        }
    executor_registration = registration["executor_registration"]
    return {
        "executor_registered": True,
        "executor_registration_path": str(executor_registration_path),
        "executor_kind": executor_registration["executor_kind"],
        "executor_ref_exposed": False,
        "executor_ref_sha256": executor_registration["executor_ref_sha256"],
        "supported_capabilities": executor_registration["supported_capabilities"],
        "credential_value_exposed": False,
        "network_execution_enabled": False,
        "live_provider_credentials_loaded": False,
    }


def _validated_normalized_summary_manifest(
    normalized_paths: list[Path],
    *,
    root: Path | None = None,
) -> list[dict[str, Any]]:
    manifest: list[dict[str, Any]] = []
    for path in normalized_paths:
        report = assert_valid_wearable_activity_summary_contract(path, root=root)
        payload = report.model_dump(mode="json")
        manifest.append(
            {
                "source_provider": payload["source_provider"],
                "source_path": payload["source_path"],
                "sha256": payload["sha256"],
                "activity_id": payload["activity_id"],
                "valid": payload["valid"],
                "summary": payload["summary"],
                "warnings": payload["warnings"],
                "data_quality": payload["data_quality"],
                "privacy": payload["privacy"],
                "boundary": payload["boundary"],
            }
        )
    return manifest


def _assert_response_capabilities_planned(
    admitted_capabilities: list[str],
    *,
    planned_capabilities: list[str],
) -> list[str]:
    admitted = _dedupe([capability.strip() for capability in admitted_capabilities if capability.strip()])
    if not admitted:
        raise ValueError("provider live response admission requires at least one capability")
    not_planned = sorted(set(admitted) - set(planned_capabilities))
    if not_planned:
        raise ValueError(
            "provider live response admission capabilities are not present in provider live request plan: "
            + ", ".join(not_planned)
        )
    return admitted


def _provider_fixture_for_live_provider(provider: str) -> ProviderApiFixture:
    if provider == "apple_healthkit_live":
        return "apple_healthkit_api"
    if provider == "garmin_health_api_live":
        return "garmin_health_api"
    raise ValueError(f"provider live response admission does not support provider: {provider}")


def _query_window(window_start_date: str, window_end_date: str) -> dict[str, str]:
    start = date.fromisoformat(window_start_date)
    end = date.fromisoformat(window_end_date)
    if end < start:
        raise ValueError("request plan end date must not be before start date")
    return {
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "precision": "date_only",
    }


def _assert_capabilities_allowed(selected_capabilities: list[str], allowed_capabilities: list[str]) -> None:
    selected = [capability.strip() for capability in selected_capabilities if capability.strip()]
    if not selected:
        raise ValueError("provider live transport request plan requires at least one capability")
    not_allowed = sorted(set(selected) - set(allowed_capabilities))
    if not_allowed:
        raise ValueError(
            "provider live transport request plan capabilities are not allowed by provider live transport preflight: "
            + ", ".join(not_allowed)
        )


def _request_slot(
    *,
    provider: ProviderLiveTransportProvider,
    capability: str,
    preflight_sha: str,
    normalized_scopes: list[str],
    query_window: dict[str, str],
) -> dict[str, Any]:
    profile = _request_profile(provider, capability)
    descriptor = {
        "provider": provider,
        "capability": capability,
        "provider_endpoint_ref": profile["provider_endpoint_ref"],
        "query_window": query_window,
        "required_scopes": profile["required_scopes"],
        "preflight_sha": preflight_sha,
    }
    return {
        "capability": capability,
        "provider_request_kind": profile["provider_request_kind"],
        "provider_endpoint_ref": profile["provider_endpoint_ref"],
        "required_scopes": profile["required_scopes"],
        "available_scopes": [scope for scope in normalized_scopes if scope in profile["required_scopes"]],
        "request_descriptor_sha256": aggregate_sha256([descriptor]),
        "request_body_exposed": False,
        "raw_response_committed": False,
        "normalized_output_target": profile["normalized_output_target"],
    }


def _request_profile(provider: ProviderLiveTransportProvider, capability: str) -> dict[str, Any]:
    profiles = {
        ("apple_healthkit_live", "activity_summary_import"): {
            "provider_request_kind": "apple_healthkit_workout_query",
            "provider_endpoint_ref": "apple_healthkit.local.workouts",
            "required_scopes": ["workout:read"],
            "normalized_output_target": "scout_wearable_sanitized_import",
        },
        ("apple_healthkit_live", "heart_rate_samples"): {
            "provider_request_kind": "apple_healthkit_heart_rate_summary_query",
            "provider_endpoint_ref": "apple_healthkit.local.heart_rate_summary",
            "required_scopes": ["heart_rate:read"],
            "normalized_output_target": "scout_wearable_sanitized_import",
        },
        ("apple_healthkit_live", "live_frame_stream"): {
            "provider_request_kind": "apple_healthkit_live_frame_summary_query",
            "provider_endpoint_ref": "apple_healthkit.local.live_frame_summary",
            "required_scopes": ["heart_rate:read"],
            "normalized_output_target": "scout_wearable_field_observation",
        },
        ("garmin_health_api_live", "activity_summary_import"): {
            "provider_request_kind": "garmin_health_activity_summary_query",
            "provider_endpoint_ref": "garmin_health.activities.summary",
            "required_scopes": ["activity:read"],
            "normalized_output_target": "scout_wearable_sanitized_import",
        },
        ("garmin_health_api_live", "heart_rate_samples"): {
            "provider_request_kind": "garmin_health_heart_rate_summary_query",
            "provider_endpoint_ref": "garmin_health.heart_rate.summary",
            "required_scopes": ["heart_rate:read"],
            "normalized_output_target": "scout_wearable_sanitized_import",
        },
        ("garmin_health_api_live", "live_frame_stream"): {
            "provider_request_kind": "garmin_health_live_frame_summary_query",
            "provider_endpoint_ref": "garmin_health.live_frame.summary",
            "required_scopes": ["heart_rate:read"],
            "normalized_output_target": "scout_wearable_field_observation",
        },
        ("garmin_health_api_live", "provider_body_energy_source_values"): {
            "provider_request_kind": "garmin_health_body_energy_summary_query",
            "provider_endpoint_ref": "garmin_health.body_energy.summary",
            "required_scopes": ["body_energy:read"],
            "normalized_output_target": "provider_source_values_only",
        },
    }
    try:
        return profiles[(provider, capability)]
    except KeyError as exc:
        raise ValueError(f"provider live transport request plan does not support capability: {capability}") from exc


def _normalize_provider_scopes(provider: ProviderLiveTransportProvider, scopes: list[str]) -> dict[str, Any]:
    normalized: list[str] = []
    unsupported_count = 0
    for scope in scopes:
        safe_scope = _normalized_scope(provider, scope)
        if safe_scope is None:
            unsupported_count += 1
        elif safe_scope not in normalized:
            normalized.append(safe_scope)
    return {
        "normalized_scopes": sorted(normalized),
        "unsupported_scope_count": unsupported_count,
    }


def _normalized_scope(provider: ProviderLiveTransportProvider, scope: str) -> str | None:
    stripped = scope.strip()
    if provider == "apple_healthkit_live":
        return _APPLE_SCOPE_MAP.get(stripped)
    if stripped in _GARMIN_SCOPE_ALLOWLIST:
        return stripped
    return None


def _review_capabilities(
    provider: ProviderLiveTransportProvider,
    *,
    normalized_scopes: list[str],
    requested_capabilities: list[str],
) -> dict[str, Any]:
    requested = _dedupe([capability.strip() for capability in requested_capabilities if capability.strip()])
    provider_supported = _PROVIDER_SUPPORTED_CAPABILITIES[provider]
    allowed: list[str] = []
    blocked: list[dict[str, str]] = []
    for capability in requested:
        if capability not in provider_supported:
            blocked.append({"capability": capability, "reason": "not_supported_by_provider"})
        elif not _capability_has_scope(provider, capability, normalized_scopes):
            blocked.append({"capability": capability, "reason": "missing_required_scope"})
        else:
            allowed.append(capability)
    return {
        "provider_supported_capabilities": provider_supported,
        "requested_capabilities": requested,
        "allowed_capabilities": allowed,
        "blocked_capabilities": blocked,
        "capability_flags_valid": not blocked,
    }


def _review_connector_capabilities(
    provider: ProviderLiveTransportProvider,
    *,
    supported_capabilities: list[str],
) -> dict[str, Any]:
    supported = _dedupe(
        [capability.strip() for capability in supported_capabilities if capability.strip()]
    )
    provider_supported = _PROVIDER_SUPPORTED_CAPABILITIES[provider]
    blocked = [
        {"capability": capability, "reason": "not_supported_by_provider"}
        for capability in supported
        if capability not in provider_supported
    ]
    return {
        "provider_supported_capabilities": provider_supported,
        "supported_capabilities": supported,
        "blocked_capabilities": blocked,
        "capability_flags_valid": not blocked,
    }


def _capability_has_scope(
    provider: ProviderLiveTransportProvider,
    capability: str,
    normalized_scopes: list[str],
) -> bool:
    scope_set = set(normalized_scopes)
    if capability == "activity_summary_import":
        if provider == "apple_healthkit_live":
            return "workout:read" in scope_set
        return "activity:read" in scope_set
    if capability in ("heart_rate_samples", "live_frame_stream"):
        return "heart_rate:read" in scope_set
    if capability == "provider_body_energy_source_values":
        return provider == "garmin_health_api_live" and "body_energy:read" in scope_set
    return False


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            result.append(value)
            seen.add(value)
    return result


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
