from __future__ import annotations

import json

import pytest

from scout_energy_models import aggregate_sha256
from scout_runtime_safety_gate_adapters import (
    EnvironmentThreatGateObservation,
    ProductionLiveConnectorHealthExecutorInvocationBoundary,
    ProductionLiveConnectorHealthExecutorInvocationRequest,
    ProductionLiveConnectorHealthExecutionBoundary,
    ProductionLiveConnectorHealthExecutionRequest,
    ProductionLiveConnectorHealthExecutionResult,
    ProductionLiveConnectorHealthIntakeBoundary,
    ProductionLiveConnectorHealthReceipt,
    ProductionLiveFieldDeviceValidationBoundary,
    ProductionLiveFieldDeviceValidationExecutionBoundary,
    ProductionLiveFieldDeviceValidationExecutionRequest,
    ProductionLiveFieldDeviceValidationExecutionResult,
    ProductionLiveFieldDeviceValidationReceipt,
    ProductionLiveFieldDeviceValidatorInvocationBoundary,
    ProductionLiveFieldDeviceValidatorInvocationRequest,
    ProductionLiveFreshnessAttestationBoundary,
    ProductionLiveFreshnessAttestationExecutionBoundary,
    ProductionLiveFreshnessAttestationExecutionRequest,
    ProductionLiveFreshnessAttestationExecutionResult,
    ProductionLiveFreshnessAttestationReceipt,
    ProductionLiveFreshnessAttestorInvocationBoundary,
    ProductionLiveFreshnessAttestorInvocationRequest,
    ProductionLiveProviderEffectReceipt,
    ProductionLiveProviderEffectReceiptIntakeBoundary,
    ProductionLiveProviderConnectorManifest,
    ProductionLiveProviderExecutionBoundary,
    ProductionLiveProviderExecutionRequest,
    ProductionLiveProviderExecutionResult,
    ProductionLiveProviderExecutorEffectBoundaryManifest,
    ProductionLiveProviderExecutorInvocationBoundary,
    ProductionLiveProviderExecutorInvocationRequest,
    ProductionLiveProviderExecutorReadinessBoundary,
    ProductionLiveProviderRequestContract,
    ProductionLiveProviderResponseIntakeBoundary,
    ProductionLiveProviderResponseReceipt,
    ProductionLiveWeatherObservation,
    build_darkness_gate_event,
    build_delay_gate_event,
    build_environment_threat_gate_event,
    build_live_provider_connector_manifest_from_health_receipt,
    build_live_field_device_validation_intake,
    build_live_freshness_attestation_intake,
    build_live_observation_from_provider_response_receipt,
    build_provider_response_receipt_from_provider_effect_receipt,
    build_pace_gate_event,
    build_production_environment_threat_gate_event,
    build_production_weather_gate_event,
    build_runtime_safety_gate_events_from_live_observations,
    build_runtime_safety_gate_events_from_fixture,
    build_weather_gate_event,
    execute_live_connector_health_check_with_client,
    execute_live_field_device_validation_with_client,
    execute_live_freshness_attestation_check_with_client,
    evaluate_live_connector_health_executor_invocation_guard,
    evaluate_live_field_device_validator_invocation_guard,
    evaluate_live_freshness_attestor_invocation_guard,
    evaluate_live_provider_executor_invocation_guard,
    evaluate_production_live_provider_request_contract,
    evaluate_live_provider_executor_effect_boundary_readiness,
    execute_live_provider_request_with_client,
)
from scout_runtime_safety_gate_models import build_runtime_safety_gate_event_batch
from scout_runtime_safety_reducer import (
    build_production_gate_residency_audit,
    build_production_live_evidence_contract_audit,
)


def test_gate_adapters_emit_sanitized_runtime_gate_events() -> None:
    events = build_runtime_safety_gate_events_from_fixture(
        {
            "pace": {
                "event_id": "pace_gate:slow-segment",
                "source_path": "outputs/runtime/pace.json",
                "observed_segment_minutes": 90,
                "reference_p75_segment_minutes": 50,
                "observed_pace_min_per_km": 18,
                "reference_p75_pace_min_per_km": 10,
                "route_pressure_review_required": True,
                "route_context": {
                    "route_id": "fixture.route",
                    "segment_id": "seg.001",
                    "checkpoint_id": "cp.001",
                },
                "evidence_refs": ["reference_segment_timing.json#seg.001"],
            },
            "delay": {
                "event_id": "delay_gate:buffer-used",
                "source_path": "outputs/runtime/delay.json",
                "delay_minutes": 38,
                "planned_buffer_minutes": 20,
                "route_context": {"segment_id": "seg.001"},
            },
            "darkness": {
                "event_id": "darkness_gate:negative-margin",
                "source_path": "outputs/runtime/darkness.json",
                "daylight_buffer_minutes": 25,
                "minutes_to_next_safe_objective": 70,
                "route_context": {"segment_id": "seg.001"},
            },
            "weather": {
                "event_id": "weather_gate:unsafe-wind",
                "source_path": "outputs/runtime/weather.json",
                "warning_level": "unsafe",
                "warning_type": "wind",
                "wind_risk": True,
                "source_age_minutes": 20,
                "route_context": {"segment_id": "seg.001"},
            },
            "environment_threat": {
                "event_id": "environment_threat_gate:washout",
                "source_path": "outputs/runtime/environment.json",
                "threat_type": "washout",
                "passability": "blocked",
                "route_blocked": True,
                "route_context": {"segment_id": "seg.001"},
            },
        }
    )
    batch = build_runtime_safety_gate_event_batch(events)
    serialized = json.dumps(batch.model_dump(mode="json"), sort_keys=True)

    assert [event.gate_id for event in events] == [
        "pace_gate",
        "delay_gate",
        "darkness_gate",
        "weather_gate",
        "environment_threat_gate",
    ]
    assert events[0].severity == "retreat_review"
    assert events[0].ln_level_candidate == "L3_RETREAT"
    assert events[1].severity == "rest"
    assert events[2].severity == "alert_review"
    assert events[3].severity == "retreat_review"
    assert events[4].severity == "retreat_review"
    assert batch.event_count == 5
    assert all(event.boundary.reducer_required for event in events)
    assert all(event.boundary.phase1_l0_l4_state_mutated is False for event in events)
    assert all(event.boundary.safety_api_called is False for event in events)
    assert all(event.boundary.medical_diagnosis is False for event in events)
    assert "/safety/" not in serialized
    assert "raw_payload" not in serialized
    assert "heartRateData" not in serialized


def test_pace_gate_uses_watch_for_mild_slowness() -> None:
    event = build_pace_gate_event(
        {
            "observed_segment_minutes": 58,
            "reference_p75_segment_minutes": 50,
        }
    )

    assert event.gate_id == "pace_gate"
    assert event.state_candidate == "pace_watch"
    assert event.severity == "watch"
    assert event.ln_transition_candidate == "candidate_watch"
    assert event.eta_delay_minutes == 8


def test_delay_gate_does_not_infer_physiologic_cause() -> None:
    event = build_delay_gate_event(
        {
            "delay_minutes": 75,
            "planned_buffer_minutes": -5,
            "camp_deadline_missed": True,
        }
    )

    assert event.gate_id == "delay_gate"
    assert event.severity == "retreat_review"
    assert any(
        "does not infer the reason for delay" in limitation
        for limitation in event.data_quality.limitations
    )
    assert "medical" not in " ".join(event.dominant_reasons).lower()


def test_darkness_and_weather_gate_keep_fixture_source_only() -> None:
    darkness = build_darkness_gate_event(
        {
            "daylight_buffer_minutes": 85,
            "minutes_to_next_safe_objective": 45,
        }
    )
    weather = build_weather_gate_event(
        {
            "warning_level": "severe",
            "warning_type": "thunderstorm",
            "lightning_risk": True,
            "source_age_minutes": 240,
        }
    )

    assert darkness.severity == "watch"
    assert darkness.route_context.daylight_buffer_minutes == 85
    assert weather.severity == "alert_review"
    assert weather.data_quality.live_network_calls_made is False
    assert weather.data_quality.stale_signal_names == ["weather_source"]


def test_environment_threat_observation_rejects_inconsistent_blocked_route() -> None:
    with pytest.raises(ValueError, match="route_blocked cannot be passable"):
        EnvironmentThreatGateObservation(
            threat_type="washout",
            passability="passable",
            route_blocked=True,
        )


def test_environment_threat_immediate_unknown_bypass_escalates_to_alert_review() -> None:
    event = build_environment_threat_gate_event(
        {
            "threat_type": "rockfall",
            "immediacy": "immediate",
            "passability": "unknown",
            "safe_bypass_known": False,
        }
    )

    assert event.gate_id == "environment_threat_gate"
    assert event.severity == "alert_review"
    assert event.ln_level_candidate == "L4_ALERT_REVIEW"
    assert event.boundary.outbound_alert_sent is False


def test_live_weather_and_threat_observation_bridge_feeds_production_audit() -> None:
    events = build_runtime_safety_gate_events_from_live_observations(
        weather={
            "source_provider": "cwa_weather_fusion_live",
            "source_path": "provider://cwa/weather/chilai-nanhua/latest",
            "event_id": "weather_gate:live-cwa-heavy-rain",
            "observed_at_offset_s": 420,
            "warning_level": "unsafe",
            "warning_type": "heavy_rain",
            "rain_risk": True,
            "source_age_minutes": 22,
            "provider_dataset_ids": ["F-C0041-001"],
            "provider_evidence_ref": "cwa://opendata/F-C0041-001/fresh-qpf",
            "freshness_attestation_ref": "attestation://freshness/weather/under-180m",
            "route_scope_ref": "runtime://route/chilai-nanhua/segment/seg.001",
            "field_attestation_ref": "field://validation/weather/leader-attested",
            "route_context": {
                "route_id": "runtime.route.chilai-nanhua",
                "segment_id": "seg.001",
                "checkpoint_id": "cp.001",
            },
        },
        environment_threat={
            "source_provider": "field_environment_threat_live",
            "source_path": "resident://environment-threat/chilai-nanhua/current",
            "event_id": "environment_threat_gate:live-route-blocked",
            "observed_at_offset_s": 450,
            "threat_type": "washout",
            "passability": "blocked",
            "immediacy": "nearby",
            "route_blocked": True,
            "current_observation_ref": "device://camera/summary/route-blocked",
            "freshness_attestation_ref": (
                "attestation://freshness/environment-threat/current"
            ),
            "route_scope_ref": "runtime://route/chilai-nanhua/segment/seg.001",
            "field_attestation_ref": (
                "operator://leader/report/route-blocked-reviewed"
            ),
            "route_context": {
                "route_id": "runtime.route.chilai-nanhua",
                "segment_id": "seg.001",
                "checkpoint_id": "cp.001",
            },
        },
    )
    audit = build_production_live_evidence_contract_audit(events)
    serialized = json.dumps(
        {
            "events": [event.model_dump(mode="json") for event in events],
            "audit": audit.model_dump(mode="json"),
        },
        sort_keys=True,
    )

    assert [event.gate_id for event in events] == [
        "weather_gate",
        "environment_threat_gate",
    ]
    assert events[0].source_gate_artifact_kind == "scout_production_live_weather_observation"
    assert events[0].source_gate_sha256 is not None
    assert events[0].severity == "retreat_review"
    assert events[0].data_quality.live_network_calls_made is False
    assert events[1].source_gate_artifact_kind == (
        "scout_production_live_environment_threat_observation"
    )
    assert events[1].source_gate_sha256 is not None
    assert events[1].severity == "retreat_review"
    assert audit.status == "all_live_contracts_ready"
    assert audit.production_weather_environment_ready is True
    assert all(row.status == "live_contract_ready" for row in audit.rows)
    assert all(event.boundary.safety_api_called is False for event in events)
    assert all(event.boundary.phase1_l0_l4_state_mutated is False for event in events)
    assert "/safety/" not in serialized
    assert "raw_payload" not in serialized


def _authorized_live_provider_request(*, gate_id: str = "weather_gate"):
    health_sha = aggregate_sha256(
        [{"connector": f"cwa-{gate_id}", "health": "healthy", "checked": "attested"}]
    )
    boundary_sha = aggregate_sha256(
        [{"boundary": f"cwa-{gate_id}-provider-effect", "review": "approved"}]
    )
    source_path = (
        "provider://cwa/weather/chilai-nanhua/latest"
        if gate_id == "weather_gate"
        else "provider://cwa/environment-threat/chilai-nanhua/current"
    )
    connector_id = (
        "connector.cwa.weather"
        if gate_id == "weather_gate"
        else "connector.cwa.environment-threat"
    )
    source_provider = (
        "cwa_weather_fusion_live"
        if gate_id == "weather_gate"
        else "cwa_environment_threat_live"
    )
    manifest = ProductionLiveProviderConnectorManifest(
        gate_id=gate_id,  # type: ignore[arg-type]
        connector_id=connector_id,
        provider_name="Central Weather Administration",
        source_provider=source_provider,
        source_path=source_path,
        provider_dataset_ids=["F-C0041-001"],
        route_scope_ref="runtime://route/chilai-nanhua/segment/seg.001",
        health_status="healthy",
        connector_health_ref=f"attestation://connector/{connector_id}/healthy",
        connector_health_sha256=health_sha,
        credential_ref="secret://scout/cwa/opendata-api-token",
    )
    request = ProductionLiveProviderRequestContract(
        gate_id=gate_id,  # type: ignore[arg-type]
        connector_id=connector_id,
        source_provider=source_provider,
        source_path=source_path,
        route_scope_ref="runtime://route/chilai-nanhua/segment/seg.001",
        connector_health_ref=f"attestation://connector/{connector_id}/healthy",
        connector_health_sha256=health_sha,
        credential_ref="secret://scout/cwa/opendata-api-token",
        idempotency_key=f"live-provider-request-{gate_id}-D1-seg001",
        execution_mode="provider_effect_boundary_request",
        reviewed_provider_effect_boundary_ref=(
            f"attestation://provider-effect/{connector_id}/reviewed"
        ),
        reviewed_provider_effect_boundary_sha256=boundary_sha,
    )
    return evaluate_production_live_provider_request_contract(manifest, request)


def _provider_executor_manifest_payload(readiness) -> dict[str, object]:
    return {
        "source_provider": "cwa_provider_executor_review",
        "source_path": "attestation://provider-effect/cwa-weather/executor-ready",
        "gate_id": readiness.gate_id,
        "connector_id": readiness.connector_id,
        "provider_request_readiness_sha256": readiness.sha256,
        "connector_manifest_sha256": readiness.manifest_sha256,
        "request_contract_sha256": readiness.request_contract_sha256,
        "source_observation_path": readiness.source_observation_path,
        "route_scope_ref": readiness.route_scope_ref,
        "connector_health_ref": readiness.connector_health_ref,
        "connector_health_sha256": readiness.connector_health_sha256,
        "credential_ref": "secret://scout/cwa/opendata-api-token",
        "provider_request_ref": readiness.provider_request_ref,
        "provider_request_sha256": readiness.provider_request_sha256,
        "provider_effect_boundary_ref": "attestation://provider-effect/cwa-weather/reviewed",
        "provider_effect_boundary_sha256": "6" * 64,
        "response_verifier_ref": "attestation://provider-response-verifier/cwa-weather",
        "response_verifier_sha256": "7" * 64,
        "freshness_attestor_ref": "attestation://freshness/weather/attestor",
        "freshness_attestor_sha256": "8" * 64,
        "field_device_validator_ref": "attestation://field-device/weather/validator",
        "field_device_validator_sha256": "9" * 64,
        "fallback_plan_ref": "attestation://provider-effect/cwa-weather/fallback",
        "fallback_plan_sha256": "a" * 64,
        "idempotency_key": "provider-executor-readiness-001",
    }


def _ready_live_provider_executor(gate_id: str = "weather_gate"):
    request_readiness = _authorized_live_provider_request(gate_id=gate_id)
    manifest = ProductionLiveProviderExecutorEffectBoundaryManifest(
        **_provider_executor_manifest_payload(request_readiness)
    )
    return request_readiness, evaluate_live_provider_executor_effect_boundary_readiness(
        request_readiness,
        manifest,
    )


def _provider_executor_invocation_payload(readiness) -> dict[str, object]:
    return {
        "gate_id": readiness.gate_id,
        "connector_id": readiness.connector_id,
        "provider_executor_readiness_sha256": readiness.sha256,
        "provider_request_readiness_sha256": (
            readiness.provider_request_readiness_sha256
        ),
        "provider_executor_manifest_sha256": (
            readiness.provider_executor_manifest_sha256
        ),
        "connector_manifest_sha256": readiness.connector_manifest_sha256,
        "request_contract_sha256": readiness.request_contract_sha256,
        "source_observation_path": readiness.source_observation_path,
        "route_scope_ref": readiness.route_scope_ref,
        "provider_request_ref": readiness.provider_request_ref,
        "provider_request_sha256": readiness.provider_request_sha256,
        "provider_effect_boundary_ref": readiness.provider_effect_boundary_ref,
        "provider_effect_boundary_sha256": (
            readiness.provider_effect_boundary_sha256
        ),
        "response_verifier_ref": readiness.response_verifier_ref,
        "response_verifier_sha256": readiness.response_verifier_sha256,
        "freshness_attestor_ref": readiness.freshness_attestor_ref,
        "freshness_attestor_sha256": readiness.freshness_attestor_sha256,
        "field_device_validator_ref": readiness.field_device_validator_ref,
        "field_device_validator_sha256": (
            readiness.field_device_validator_sha256
        ),
        "fallback_plan_ref": readiness.fallback_plan_ref,
        "fallback_plan_sha256": readiness.fallback_plan_sha256,
        "operator_identity_ref": "operator://identity/incident-commander-01",
        "operator_identity_sha256": "c" * 64,
        "operator_role": "incident_commander",
        "explicit_confirmation": True,
        "confirmation_phrase": "INVOKE SCOUT LIVE PROVIDER",
        "idempotency_key": "provider-executor-invocation-001",
    }


def _provider_effect_receipt_payload(invocation) -> dict[str, object]:
    return {
        "source_provider": "cwa_weather_fusion_live",
        "source_path": "provider://cwa/weather/chilai-nanhua/latest/effect-001",
        "gate_id": invocation.gate_id,
        "connector_id": invocation.connector_id,
        "provider_executor_invocation_sha256": invocation.sha256,
        "provider_executor_readiness_sha256": (
            invocation.provider_executor_readiness_sha256
        ),
        "provider_request_readiness_sha256": (
            invocation.provider_request_readiness_sha256
        ),
        "provider_executor_manifest_sha256": (
            invocation.provider_executor_manifest_sha256
        ),
        "connector_manifest_sha256": invocation.connector_manifest_sha256,
        "request_contract_sha256": invocation.request_contract_sha256,
        "source_observation_path": invocation.source_observation_path,
        "route_scope_ref": invocation.route_scope_ref,
        "provider_request_ref": invocation.provider_request_ref,
        "provider_request_sha256": invocation.provider_request_sha256,
        "provider_execution_ref": invocation.provider_execution_ref,
        "provider_execution_sha256": invocation.provider_execution_sha256,
        "provider_dataset_ids": ["F-C0041-001"],
        "provider_evidence_ref": "cwa://opendata/F-C0041-001/weather-effect-001",
        "provider_evidence_sha256": "e" * 64,
        "freshness_attestation_ref": "attestation://freshness/weather/effect-001",
        "freshness_attestation_sha256": "f" * 64,
        "source_age_minutes": 16,
        "freshness_requirement_minutes": 180,
        "response_status": "success",
        "observed_at_offset_s": 540,
        "warning_level": "unsafe",
        "warning_type": "heavy_rain",
        "rain_risk": True,
        "route_context": {
            "route_id": "runtime.route.chilai-nanhua",
            "segment_id": "seg.001",
            "checkpoint_id": "cp.001",
        },
        "executor_reported_provider_network_request_performed": True,
        "executor_reported_real_provider_api_called": True,
    }


def _connector_health_invocation_payload() -> dict[str, object]:
    return {
        "gate_id": "weather_gate",
        "connector_id": "connector.cwa.weather",
        "provider_name": "Central Weather Administration",
        "source_provider": "cwa_weather_fusion_live",
        "source_path": "provider://cwa/weather/chilai-nanhua/latest",
        "provider_dataset_ids": ["F-C0041-001"],
        "route_scope_ref": "runtime://route/chilai-nanhua/segment/seg.001",
        "credential_ref": "secret://scout/cwa/opendata-api-token",
        "freshness_requirement_minutes": 180,
        "reviewed_connector_health_effect_boundary_ref": (
            "attestation://connector-health/cwa-weather/effect-boundary"
        ),
        "reviewed_connector_health_effect_boundary_sha256": "1" * 64,
        "fallback_plan_ref": "attestation://connector-health/cwa-weather/fallback",
        "fallback_plan_sha256": "2" * 64,
        "operator_identity_ref": "operator://identity/incident-commander-01",
        "operator_identity_sha256": "3" * 64,
        "operator_role": "incident_commander",
        "explicit_confirmation": True,
        "confirmation_phrase": "INVOKE SCOUT CONNECTOR HEALTH",
        "idempotency_key": "connector-health-invocation-001",
    }


def _connector_health_receipt_payload() -> dict[str, object]:
    return {
        "source_provider": "cwa_weather_fusion_live",
        "source_path": "provider://cwa/weather/chilai-nanhua/latest",
        "gate_id": "weather_gate",
        "connector_id": "connector.cwa.weather",
        "provider_name": "Central Weather Administration",
        "provider_dataset_ids": ["F-C0041-001"],
        "route_scope_ref": "runtime://route/chilai-nanhua/segment/seg.001",
        "health_status": "healthy",
        "connector_health_ref": "attestation://connector/cwa-weather/healthy",
        "connector_health_sha256": "d" * 64,
        "credential_ref": "secret://scout/cwa/opendata-api-token",
        "freshness_requirement_minutes": 180,
        "executor_reported_connector_health_check_performed": True,
        "executor_reported_provider_network_request_performed": True,
        "executor_reported_real_provider_api_called": True,
    }


def test_live_connector_health_invocation_guard_binds_health_intake() -> None:
    invocation = evaluate_live_connector_health_executor_invocation_guard(
        ProductionLiveConnectorHealthExecutorInvocationRequest(
            **_connector_health_invocation_payload()
        )
    )
    health_receipt = ProductionLiveConnectorHealthReceipt(
        **{
            **_connector_health_receipt_payload(),
            "connector_health_invocation_sha256": invocation.sha256,
            "connector_health_execution_ref": (
                invocation.connector_health_execution_ref
            ),
            "connector_health_execution_sha256": (
                invocation.connector_health_execution_sha256
            ),
        }
    )

    intake = build_live_provider_connector_manifest_from_health_receipt(
        health_receipt,
        connector_health_invocation=invocation,
    )

    assert invocation.status == "connector_health_executor_invocation_authorized"
    assert invocation.connector_health_executor_invocation_authorized is True
    assert invocation.connector_health_effect_boundary_present is True
    assert invocation.fallback_plan_present is True
    assert invocation.credential_ref_present is True
    assert invocation.operator_identity_present is True
    assert invocation.explicit_confirmation_present is True
    assert invocation.connector_health_execution_ref is not None
    assert invocation.connector_health_execution_sha256 is not None
    assert invocation.connector_health_checked_by_guard is False
    assert invocation.provider_network_request_performed_by_guard is False
    assert invocation.real_provider_api_called_by_guard is False
    assert invocation.runtime_ingest_performed_by_guard is False
    assert invocation.safety_api_called is False
    assert intake.status == "connector_manifest_prepared"
    assert intake.connector_health_invocation_sha256 == invocation.sha256
    assert intake.connector_health_execution_ref == (
        invocation.connector_health_execution_ref
    )
    assert intake.connector_health_invocation_authorized is True
    assert intake.connector_health_invocation_lineage_match is True
    assert intake.connector_manifest is not None
    assert intake.connector_health_checked_by_intake is False
    assert intake.provider_network_request_performed_by_intake is False
    assert intake.safety_api_called is False


def test_live_connector_health_invocation_guard_fails_closed() -> None:
    base_request = _connector_health_invocation_payload()
    authorized = evaluate_live_connector_health_executor_invocation_guard(base_request)

    missing_boundary = evaluate_live_connector_health_executor_invocation_guard(
        {
            **base_request,
            "reviewed_connector_health_effect_boundary_ref": None,
            "reviewed_connector_health_effect_boundary_sha256": None,
        }
    )
    missing_secret = evaluate_live_connector_health_executor_invocation_guard(
        {**base_request, "credential_ref": None}
    )
    missing_operator = evaluate_live_connector_health_executor_invocation_guard(
        {
            **base_request,
            "operator_identity_ref": None,
            "operator_identity_sha256": None,
        }
    )
    missing_confirmation = evaluate_live_connector_health_executor_invocation_guard(
        {**base_request, "confirmation_phrase": "CHECK CONNECTOR NOW"}
    )
    blocked_invocation = authorized.model_copy(
        update={
            "status": "blocked_connector_health_operator_identity_missing",
            "connector_health_executor_invocation_authorized": False,
            "operator_identity_present": False,
        }
    )
    not_authorized = build_live_provider_connector_manifest_from_health_receipt(
        {
            **_connector_health_receipt_payload(),
            "connector_health_invocation_sha256": authorized.sha256,
            "connector_health_execution_ref": authorized.connector_health_execution_ref,
            "connector_health_execution_sha256": (
                authorized.connector_health_execution_sha256
            ),
        },
        connector_health_invocation=blocked_invocation,
    )
    mismatch = build_live_provider_connector_manifest_from_health_receipt(
        {
            **_connector_health_receipt_payload(),
            "connector_id": "connector.cwa.other",
            "connector_health_invocation_sha256": authorized.sha256,
            "connector_health_execution_ref": authorized.connector_health_execution_ref,
            "connector_health_execution_sha256": (
                authorized.connector_health_execution_sha256
            ),
        },
        connector_health_invocation=authorized,
    )

    assert missing_boundary.status == (
        "blocked_connector_health_effect_boundary_missing"
    )
    assert missing_secret.status == "blocked_requires_credential_ref"
    assert missing_operator.status == "blocked_connector_health_operator_identity_missing"
    assert missing_confirmation.status == (
        "blocked_explicit_connector_health_confirmation_missing"
    )
    assert missing_confirmation.connector_health_checked_by_guard is False
    assert not_authorized.status == (
        "blocked_connector_health_invocation_not_authorized"
    )
    assert not_authorized.connector_manifest is None
    assert mismatch.status == "blocked_connector_health_invocation_lineage_mismatch"
    assert mismatch.connector_manifest_prepared is False
    assert mismatch.safety_api_called is False
    with pytest.raises(ValueError, match="cannot perform effects"):
        ProductionLiveConnectorHealthExecutorInvocationBoundary(
            connector_health_checked_by_guard=True
        )
    with pytest.raises(ValueError, match="cannot embed raw payloads"):
        ProductionLiveConnectorHealthExecutorInvocationRequest(
            **{**base_request, "raw_provider_payload_embedded": True}
        )


def _connector_health_execution_request_payload(
    invocation: object,
) -> dict[str, object]:
    return {
        "gate_id": invocation.gate_id,
        "connector_id": invocation.connector_id,
        "provider_name": invocation.provider_name,
        "source_observation_path": invocation.source_observation_path,
        "route_scope_ref": invocation.route_scope_ref,
        "connector_health_invocation_sha256": invocation.sha256,
        "connector_health_invocation_request_sha256": (
            invocation.connector_health_invocation_request_sha256
        ),
        "connector_health_execution_ref": invocation.connector_health_execution_ref,
        "connector_health_execution_sha256": (
            invocation.connector_health_execution_sha256
        ),
        "provider_dataset_ids": invocation.provider_dataset_ids,
        "reviewed_connector_health_effect_boundary_ref": (
            invocation.reviewed_connector_health_effect_boundary_ref
        ),
        "reviewed_connector_health_effect_boundary_sha256": (
            invocation.reviewed_connector_health_effect_boundary_sha256
        ),
        "fallback_plan_ref": invocation.fallback_plan_ref,
        "fallback_plan_sha256": invocation.fallback_plan_sha256,
        "credential_ref": invocation.credential_ref,
        "operator_identity_ref": invocation.operator_identity_ref,
        "operator_identity_sha256": invocation.operator_identity_sha256,
        "operator_role": invocation.operator_role,
        "idempotency_key": invocation.idempotency_key,
    }


def _fake_connector_health_execution_result(
    request: ProductionLiveConnectorHealthExecutionRequest,
) -> dict[str, object]:
    payload = request.model_dump(mode="json")
    assert payload["credential_ref"] == "secret://scout/cwa/opendata-api-token"
    assert "credential_value" not in payload
    return {
        "source_provider": "cwa_weather_fusion_live",
        "source_path": request.source_observation_path,
        "provider_dataset_ids": request.provider_dataset_ids,
        "health_status": "healthy",
        "connector_health_ref": "attestation://connector/cwa-weather/healthy",
        "connector_health_sha256": "d" * 64,
        "route_scoped_request_supported": True,
        "freshness_attestation_supported": True,
        "effect_boundary_required": True,
        "executor_reported_connector_health_check_performed": True,
        "executor_reported_provider_network_request_performed": True,
        "executor_reported_real_provider_api_called": True,
    }


def test_live_connector_health_executor_harness_emits_health_receipt() -> None:
    invocation = evaluate_live_connector_health_executor_invocation_guard(
        ProductionLiveConnectorHealthExecutorInvocationRequest(
            **_connector_health_invocation_payload()
        )
    )
    seen_requests: list[ProductionLiveConnectorHealthExecutionRequest] = []

    def health_client(
        request: ProductionLiveConnectorHealthExecutionRequest,
    ) -> dict[str, object]:
        seen_requests.append(request)
        return _fake_connector_health_execution_result(request)

    execution = execute_live_connector_health_check_with_client(
        invocation,
        health_client,
    )
    intake = build_live_provider_connector_manifest_from_health_receipt(
        execution.health_receipt or {},
        connector_health_invocation=invocation,
    )

    assert execution.status == "connector_health_receipt_emitted"
    assert execution.connector_health_invocation_authorized is True
    assert execution.connector_health_client_called is True
    assert execution.connector_health_client_result_valid is True
    assert execution.connector_health_client_effect_present is True
    assert execution.health_receipt is not None
    assert execution.health_receipt_sha256 is not None
    assert execution.runtime_ingest_performed_by_executor is False
    assert execution.safety_api_called is False
    assert execution.phase1_l0_l4_state_mutated is False
    assert execution.outbound_transport_invoked is False
    assert execution.hardware_control_performed is False
    assert len(seen_requests) == 1
    assert seen_requests[0].connector_health_invocation_sha256 == invocation.sha256
    assert seen_requests[0].credential_ref == (
        "secret://scout/cwa/opendata-api-token"
    )
    assert seen_requests[0].safety_api_called is False
    assert intake.status == "connector_manifest_prepared"
    assert intake.connector_manifest is not None
    assert intake.connector_health_invocation_authorized is True
    assert intake.connector_health_invocation_lineage_match is True


def test_live_connector_health_executor_harness_fails_closed() -> None:
    invocation = evaluate_live_connector_health_executor_invocation_guard(
        _connector_health_invocation_payload()
    )
    calls: list[ProductionLiveConnectorHealthExecutionRequest] = []

    def health_client(
        request: ProductionLiveConnectorHealthExecutionRequest,
    ) -> dict[str, object]:
        calls.append(request)
        return _fake_connector_health_execution_result(request)

    blocked_invocation = invocation.model_copy(
        update={
            "status": "blocked_connector_health_operator_identity_missing",
            "connector_health_executor_invocation_authorized": False,
            "operator_identity_present": False,
        }
    )

    not_authorized = execute_live_connector_health_check_with_client(
        blocked_invocation,
        health_client,
    )
    invalid_result = execute_live_connector_health_check_with_client(
        invocation,
        lambda request: {
            **_fake_connector_health_execution_result(request),
            "raw_provider_payload_embedded": True,
        },
    )
    missing_effect = execute_live_connector_health_check_with_client(
        invocation,
        lambda request: {
            **_fake_connector_health_execution_result(request),
            "executor_reported_connector_health_check_performed": False,
        },
    )

    assert not_authorized.status == "blocked_connector_health_invocation_not_authorized"
    assert not_authorized.connector_health_client_called is False
    assert invalid_result.status == "blocked_connector_health_client_result_invalid"
    assert invalid_result.health_receipt is None
    assert missing_effect.status == "blocked_connector_health_client_effect_missing"
    assert missing_effect.health_receipt is None
    assert missing_effect.safety_api_called is False
    assert calls == []
    with pytest.raises(ValueError, match="cannot perform runtime effects"):
        ProductionLiveConnectorHealthExecutionBoundary(safety_api_called=True)
    with pytest.raises(ValueError, match="cannot embed raw payloads"):
        ProductionLiveConnectorHealthExecutionResult(
            **{
                **_fake_connector_health_execution_result(
                    ProductionLiveConnectorHealthExecutionRequest(
                        **_connector_health_execution_request_payload(
                            invocation
                        )
                    )
                ),
                "raw_provider_payload_embedded": True,
            }
        )


def test_live_connector_health_receipt_intake_prepares_request_manifest() -> None:
    receipt = ProductionLiveConnectorHealthReceipt(**_connector_health_receipt_payload())

    intake = build_live_provider_connector_manifest_from_health_receipt(receipt)
    manifest = intake.connector_manifest
    assert manifest is not None
    request = ProductionLiveProviderRequestContract(
        gate_id=manifest.gate_id,
        connector_id=manifest.connector_id,
        source_provider=manifest.source_provider,
        source_path=manifest.source_path,
        route_scope_ref=manifest.route_scope_ref,
        connector_health_ref=manifest.connector_health_ref,
        connector_health_sha256=manifest.connector_health_sha256,
        credential_ref=manifest.credential_ref,
        freshness_requirement_minutes=manifest.freshness_requirement_minutes,
        idempotency_key="weather-request-from-health-intake-001",
        execution_mode="provider_effect_boundary_request",
        reviewed_provider_effect_boundary_ref=(
            "attestation://provider-effect/cwa-weather/reviewed"
        ),
        reviewed_provider_effect_boundary_sha256="e" * 64,
    )
    readiness = evaluate_production_live_provider_request_contract(
        manifest,
        request,
    )

    assert intake.status == "connector_manifest_prepared"
    assert intake.connector_manifest_prepared is True
    assert intake.connector_health_check_performed is True
    assert intake.connector_health_evidence_present is True
    assert intake.connector_healthy is True
    assert intake.credential_ref_present is True
    assert intake.connector_health_checked_by_intake is False
    assert intake.provider_network_request_performed_by_intake is False
    assert intake.real_provider_api_called_by_intake is False
    assert intake.runtime_ingest_performed_by_intake is False
    assert intake.safety_api_called is False
    assert intake.phase1_l0_l4_state_mutated is False
    assert manifest.health_status == "healthy"
    assert manifest.connector_health_ref == receipt.connector_health_ref
    assert readiness.status == "provider_request_boundary_authorized"
    assert readiness.provider_request_boundary_authorized is True


def test_live_connector_health_receipt_intake_fails_closed() -> None:
    base_receipt = _connector_health_receipt_payload()

    missing_check = build_live_provider_connector_manifest_from_health_receipt(
        {
            **base_receipt,
            "executor_reported_connector_health_check_performed": False,
        }
    )
    missing_evidence = build_live_provider_connector_manifest_from_health_receipt(
        {**base_receipt, "connector_health_ref": None}
    )
    degraded = build_live_provider_connector_manifest_from_health_receipt(
        {**base_receipt, "health_status": "degraded"}
    )
    missing_secret = build_live_provider_connector_manifest_from_health_receipt(
        {**base_receipt, "credential_ref": None}
    )

    assert missing_check.status == "blocked_connector_health_check_missing"
    assert missing_check.connector_manifest is None
    assert missing_evidence.status == "blocked_connector_health_evidence_missing"
    assert degraded.status == "blocked_connector_health_not_ready"
    assert missing_secret.status == "blocked_requires_credential_ref"
    assert missing_secret.provider_network_request_performed_by_intake is False
    assert missing_secret.safety_api_called is False
    with pytest.raises(ValueError, match="cannot perform effects"):
        ProductionLiveConnectorHealthIntakeBoundary(
            provider_network_request_performed_by_intake=True
        )
    with pytest.raises(ValueError, match="cannot embed raw payloads"):
        ProductionLiveConnectorHealthReceipt(
            **{**base_receipt, "raw_provider_payload_embedded": True}
        )


def test_live_provider_executor_readiness_requires_reviewed_boundary() -> None:
    request_readiness = _authorized_live_provider_request(gate_id="weather_gate")
    manifest = ProductionLiveProviderExecutorEffectBoundaryManifest(
        **_provider_executor_manifest_payload(request_readiness)
    )

    readiness = evaluate_live_provider_executor_effect_boundary_readiness(
        request_readiness,
        manifest,
    )

    assert readiness.status == "ready_for_reviewed_provider_effect_boundary"
    assert readiness.ready_for_reviewed_provider_effect_boundary is True
    assert readiness.provider_request_authorized is True
    assert readiness.lineage_match is True
    assert readiness.provider_executor_boundary_present is True
    assert readiness.credential_ref_present is True
    assert readiness.response_verifier_present is True
    assert readiness.freshness_attestor_present is True
    assert readiness.field_device_validator_present is True
    assert readiness.fallback_plan_present is True
    assert readiness.provider_request_ref == request_readiness.provider_request_ref
    assert readiness.provider_request_sha256 == request_readiness.provider_request_sha256
    assert readiness.connector_health_checked_by_readiness is False
    assert readiness.provider_network_request_performed_by_readiness is False
    assert readiness.real_provider_api_called_by_readiness is False
    assert readiness.runtime_ingest_performed_by_readiness is False
    assert readiness.safety_api_called is False
    assert readiness.phase1_l0_l4_state_mutated is False
    assert readiness.boundary.provider_network_request_performed_by_readiness is False


def test_live_provider_executor_readiness_fails_closed() -> None:
    request_readiness = _authorized_live_provider_request(gate_id="weather_gate")
    base_manifest = _provider_executor_manifest_payload(request_readiness)
    dry_run_readiness = request_readiness.model_copy(
        update={
            "status": "dry_run_ready",
            "provider_request_boundary_authorized": False,
            "provider_request_ref": None,
            "provider_request_sha256": None,
        }
    )

    unauthorized = evaluate_live_provider_executor_effect_boundary_readiness(
        dry_run_readiness,
        base_manifest,
    )
    mismatch = evaluate_live_provider_executor_effect_boundary_readiness(
        request_readiness,
        {**base_manifest, "connector_id": "connector.cwa.other"},
    )
    missing_boundary = evaluate_live_provider_executor_effect_boundary_readiness(
        request_readiness,
        {**base_manifest, "provider_effect_boundary_ref": None},
    )
    missing_verifier = evaluate_live_provider_executor_effect_boundary_readiness(
        request_readiness,
        {**base_manifest, "response_verifier_ref": None},
    )
    missing_freshness = evaluate_live_provider_executor_effect_boundary_readiness(
        request_readiness,
        {**base_manifest, "freshness_attestor_ref": None},
    )
    missing_field = evaluate_live_provider_executor_effect_boundary_readiness(
        request_readiness,
        {**base_manifest, "field_device_validator_ref": None},
    )
    missing_fallback = evaluate_live_provider_executor_effect_boundary_readiness(
        request_readiness,
        {**base_manifest, "fallback_plan_ref": None},
    )

    assert unauthorized.status == "blocked_provider_request_not_authorized"
    assert unauthorized.ready_for_reviewed_provider_effect_boundary is False
    assert mismatch.status == "blocked_provider_executor_lineage_mismatch"
    assert missing_boundary.status == "blocked_provider_executor_boundary_missing"
    assert missing_verifier.status == "blocked_response_verifier_missing"
    assert missing_freshness.status == "blocked_freshness_attestor_missing"
    assert missing_field.status == "blocked_field_device_validator_missing"
    assert missing_fallback.status == "blocked_fallback_plan_missing"
    assert missing_fallback.provider_network_request_performed_by_readiness is False
    assert missing_fallback.safety_api_called is False
    with pytest.raises(ValueError, match="cannot perform effects"):
        ProductionLiveProviderExecutorReadinessBoundary(
            real_provider_api_called_by_readiness=True
        )
    with pytest.raises(ValueError, match="cannot embed raw payloads"):
        ProductionLiveProviderExecutorEffectBoundaryManifest(
            **{**base_manifest, "raw_provider_payload_embedded": True}
        )


def test_live_provider_executor_invocation_guard_binds_response_intake() -> None:
    request_readiness, executor_readiness = _ready_live_provider_executor(
        gate_id="weather_gate"
    )
    invocation_request = ProductionLiveProviderExecutorInvocationRequest(
        **_provider_executor_invocation_payload(executor_readiness)
    )

    invocation = evaluate_live_provider_executor_invocation_guard(
        executor_readiness,
        invocation_request,
    )
    response_receipt = ProductionLiveProviderResponseReceipt(
        **{
            **_provider_response_receipt_payload(
                request_readiness,
                gate_id="weather_gate",
            ),
            "provider_executor_invocation_sha256": invocation.sha256,
            "provider_execution_ref": invocation.provider_execution_ref,
            "provider_execution_sha256": invocation.provider_execution_sha256,
        }
    )
    intake = build_live_observation_from_provider_response_receipt(
        request_readiness,
        response_receipt,
        provider_executor_invocation=invocation,
    )
    event = build_production_weather_gate_event(intake.weather_observation or {})

    assert invocation.status == "provider_executor_invocation_authorized"
    assert invocation.provider_executor_invocation_authorized is True
    assert invocation.provider_executor_ready is True
    assert invocation.lineage_match is True
    assert invocation.operator_identity_present is True
    assert invocation.explicit_confirmation_present is True
    assert invocation.provider_execution_ref is not None
    assert invocation.provider_execution_sha256 is not None
    assert invocation.provider_network_request_performed_by_guard is False
    assert invocation.real_provider_api_called_by_guard is False
    assert invocation.runtime_ingest_performed_by_guard is False
    assert invocation.safety_api_called is False
    assert invocation.phase1_l0_l4_state_mutated is False
    assert intake.status == "live_observation_prepared"
    assert intake.provider_executor_invocation_sha256 == invocation.sha256
    assert intake.provider_execution_ref == invocation.provider_execution_ref
    assert intake.provider_execution_sha256 == invocation.provider_execution_sha256
    assert intake.provider_executor_invocation_authorized is True
    assert intake.provider_executor_invocation_lineage_match is True
    assert invocation.provider_execution_ref in event.evidence_refs
    assert event.boundary.safety_api_called is False
    assert event.boundary.phase1_l0_l4_state_mutated is False


def test_live_provider_executor_invocation_guard_fails_closed() -> None:
    request_readiness, executor_readiness = _ready_live_provider_executor(
        gate_id="weather_gate"
    )
    base_request = _provider_executor_invocation_payload(executor_readiness)
    blocked_readiness = executor_readiness.model_copy(
        update={
            "status": "blocked_response_verifier_missing",
            "ready_for_reviewed_provider_effect_boundary": False,
            "response_verifier_present": False,
        }
    )

    not_ready = evaluate_live_provider_executor_invocation_guard(
        blocked_readiness,
        base_request,
    )
    mismatch = evaluate_live_provider_executor_invocation_guard(
        executor_readiness,
        {**base_request, "connector_id": "connector.cwa.other"},
    )
    missing_operator = evaluate_live_provider_executor_invocation_guard(
        executor_readiness,
        {
            **base_request,
            "operator_identity_ref": None,
            "operator_identity_sha256": None,
        },
    )
    missing_confirmation = evaluate_live_provider_executor_invocation_guard(
        executor_readiness,
        {**base_request, "confirmation_phrase": "CALL PROVIDER NOW"},
    )

    invocation = evaluate_live_provider_executor_invocation_guard(
        executor_readiness,
        base_request,
    )
    response_receipt = ProductionLiveProviderResponseReceipt(
        **{
            **_provider_response_receipt_payload(
                request_readiness,
                gate_id="weather_gate",
            ),
            "provider_executor_invocation_sha256": "0" * 64,
            "provider_execution_ref": invocation.provider_execution_ref,
            "provider_execution_sha256": invocation.provider_execution_sha256,
        }
    )
    bad_response = build_live_observation_from_provider_response_receipt(
        request_readiness,
        response_receipt,
        provider_executor_invocation=invocation,
    )

    assert not_ready.status == "blocked_provider_executor_not_ready"
    assert not_ready.provider_executor_invocation_authorized is False
    assert mismatch.status == "blocked_provider_invocation_lineage_mismatch"
    assert missing_operator.status == "blocked_provider_operator_identity_missing"
    assert missing_confirmation.status == (
        "blocked_explicit_provider_invocation_confirmation_missing"
    )
    assert missing_confirmation.provider_network_request_performed_by_guard is False
    assert missing_confirmation.safety_api_called is False
    assert bad_response.status == (
        "blocked_provider_executor_invocation_lineage_mismatch"
    )
    assert bad_response.live_observation_prepared is False
    assert bad_response.safety_api_called is False
    with pytest.raises(ValueError, match="cannot perform effects"):
        ProductionLiveProviderExecutorInvocationBoundary(
            provider_network_request_performed_by_guard=True
        )
    with pytest.raises(ValueError, match="cannot embed raw payloads"):
        ProductionLiveProviderExecutorInvocationRequest(
            **{**base_request, "raw_provider_payload_embedded": True}
        )


def _provider_execution_request_payload(invocation) -> dict[str, object]:
    return {
        "gate_id": invocation.gate_id,
        "connector_id": invocation.connector_id,
        "provider_executor_invocation_sha256": invocation.sha256,
        "provider_executor_readiness_sha256": (
            invocation.provider_executor_readiness_sha256
        ),
        "provider_request_readiness_sha256": (
            invocation.provider_request_readiness_sha256
        ),
        "provider_executor_manifest_sha256": (
            invocation.provider_executor_manifest_sha256
        ),
        "connector_manifest_sha256": invocation.connector_manifest_sha256,
        "request_contract_sha256": invocation.request_contract_sha256,
        "source_observation_path": invocation.source_observation_path,
        "route_scope_ref": invocation.route_scope_ref,
        "provider_request_ref": invocation.provider_request_ref,
        "provider_request_sha256": invocation.provider_request_sha256,
        "provider_execution_ref": invocation.provider_execution_ref,
        "provider_execution_sha256": invocation.provider_execution_sha256,
        "provider_effect_boundary_ref": invocation.provider_effect_boundary_ref,
        "provider_effect_boundary_sha256": (
            invocation.provider_effect_boundary_sha256
        ),
        "response_verifier_ref": invocation.response_verifier_ref,
        "response_verifier_sha256": invocation.response_verifier_sha256,
        "freshness_attestor_ref": invocation.freshness_attestor_ref,
        "freshness_attestor_sha256": invocation.freshness_attestor_sha256,
        "field_device_validator_ref": invocation.field_device_validator_ref,
        "field_device_validator_sha256": invocation.field_device_validator_sha256,
        "fallback_plan_ref": invocation.fallback_plan_ref,
        "fallback_plan_sha256": invocation.fallback_plan_sha256,
        "operator_identity_ref": invocation.operator_identity_ref,
        "operator_identity_sha256": invocation.operator_identity_sha256,
        "operator_role": invocation.operator_role,
        "credential_ref_present": True,
        "idempotency_key": invocation.idempotency_key,
    }


def _fake_provider_execution_result(
    request: ProductionLiveProviderExecutionRequest,
) -> dict[str, object]:
    payload = request.model_dump(mode="json")
    assert "credential_ref" not in payload
    assert payload["credential_ref_present"] is True
    return {
        "source_provider": "cwa_weather_fusion_live",
        "source_path": "provider://cwa/weather/chilai-nanhua/latest/effect-001",
        "source_observation_path": request.source_observation_path,
        "provider_dataset_ids": ["F-C0041-001"],
        "provider_evidence_ref": "cwa://opendata/F-C0041-001/weather-effect-001",
        "provider_evidence_sha256": "e" * 64,
        "freshness_attestation_ref": "attestation://freshness/weather/effect-001",
        "freshness_attestation_sha256": "f" * 64,
        "source_age_minutes": 16,
        "freshness_requirement_minutes": 180,
        "response_status": "success",
        "observed_at_offset_s": 540,
        "warning_level": "unsafe",
        "warning_type": "heavy_rain",
        "rain_risk": True,
        "route_context": {
            "route_id": "runtime.route.chilai-nanhua",
            "segment_id": "seg.001",
            "checkpoint_id": "cp.001",
        },
        "executor_reported_provider_network_request_performed": True,
        "executor_reported_real_provider_api_called": True,
    }


def test_live_provider_executor_harness_emits_effect_receipt() -> None:
    request_readiness, executor_readiness = _ready_live_provider_executor(
        gate_id="weather_gate"
    )
    invocation = evaluate_live_provider_executor_invocation_guard(
        executor_readiness,
        _provider_executor_invocation_payload(executor_readiness),
    )
    seen_requests: list[ProductionLiveProviderExecutionRequest] = []

    def provider_client(
        request: ProductionLiveProviderExecutionRequest,
    ) -> dict[str, object]:
        seen_requests.append(request)
        return _fake_provider_execution_result(request)

    execution = execute_live_provider_request_with_client(
        executor_readiness,
        invocation,
        provider_client,
    )
    effect_intake = build_provider_response_receipt_from_provider_effect_receipt(
        invocation,
        execution.provider_effect_receipt or {},
    )
    response_intake = build_live_observation_from_provider_response_receipt(
        request_readiness,
        effect_intake.response_receipt or {},
        provider_executor_invocation=invocation,
    )

    assert execution.status == "provider_effect_receipt_emitted"
    assert execution.provider_executor_ready is True
    assert execution.provider_executor_invocation_authorized is True
    assert execution.provider_execution_lineage_match is True
    assert execution.provider_client_called is True
    assert execution.provider_client_result_valid is True
    assert execution.provider_client_effect_present is True
    assert execution.provider_effect_receipt is not None
    assert execution.provider_effect_receipt_sha256 is not None
    assert execution.runtime_ingest_performed_by_executor is False
    assert execution.safety_api_called is False
    assert execution.phase1_l0_l4_state_mutated is False
    assert execution.outbound_transport_invoked is False
    assert execution.hardware_control_performed is False
    assert len(seen_requests) == 1
    assert seen_requests[0].provider_executor_invocation_sha256 == invocation.sha256
    assert seen_requests[0].provider_request_ref == invocation.provider_request_ref
    assert seen_requests[0].provider_execution_ref == invocation.provider_execution_ref
    assert seen_requests[0].runtime_ingest_performed_by_executor is False
    assert seen_requests[0].safety_api_called is False
    assert effect_intake.status == "provider_response_receipt_prepared"
    assert effect_intake.provider_effect_lineage_match is True
    assert response_intake.status == "live_observation_prepared"


def test_live_provider_executor_harness_fails_closed() -> None:
    _, executor_readiness = _ready_live_provider_executor(gate_id="weather_gate")
    invocation = evaluate_live_provider_executor_invocation_guard(
        executor_readiness,
        _provider_executor_invocation_payload(executor_readiness),
    )
    client_calls: list[ProductionLiveProviderExecutionRequest] = []

    def provider_client(
        request: ProductionLiveProviderExecutionRequest,
    ) -> dict[str, object]:
        client_calls.append(request)
        return _fake_provider_execution_result(request)

    blocked_readiness = executor_readiness.model_copy(
        update={
            "status": "blocked_response_verifier_missing",
            "ready_for_reviewed_provider_effect_boundary": False,
            "response_verifier_present": False,
        }
    )
    blocked_invocation = invocation.model_copy(
        update={
            "status": "blocked_provider_operator_identity_missing",
            "provider_executor_invocation_authorized": False,
            "operator_identity_present": False,
        }
    )
    mismatched_readiness = executor_readiness.model_copy(
        update={"connector_id": "connector.cwa.other"}
    )

    not_ready = execute_live_provider_request_with_client(
        blocked_readiness,
        invocation,
        provider_client,
    )
    not_authorized = execute_live_provider_request_with_client(
        executor_readiness,
        blocked_invocation,
        provider_client,
    )
    mismatch = execute_live_provider_request_with_client(
        mismatched_readiness,
        invocation,
        provider_client,
    )
    invalid_result = execute_live_provider_request_with_client(
        executor_readiness,
        invocation,
        lambda request: {
            **_fake_provider_execution_result(request),
            "raw_provider_payload_embedded": True,
        },
    )
    missing_effect = execute_live_provider_request_with_client(
        executor_readiness,
        invocation,
        lambda request: {
            **_fake_provider_execution_result(request),
            "executor_reported_real_provider_api_called": False,
        },
    )

    assert not_ready.status == "blocked_provider_executor_not_ready"
    assert not_ready.provider_client_called is False
    assert not_authorized.status == (
        "blocked_provider_executor_invocation_not_authorized"
    )
    assert not_authorized.provider_client_called is False
    assert mismatch.status == "blocked_provider_execution_lineage_mismatch"
    assert mismatch.provider_client_called is False
    assert invalid_result.status == "blocked_provider_client_result_invalid"
    assert invalid_result.provider_effect_receipt is None
    assert missing_effect.status == "blocked_provider_client_effect_missing"
    assert missing_effect.provider_effect_receipt is None
    assert missing_effect.safety_api_called is False
    assert client_calls == []
    with pytest.raises(ValueError, match="cannot perform runtime effects"):
        ProductionLiveProviderExecutionBoundary(safety_api_called=True)
    with pytest.raises(ValueError, match="cannot embed raw payloads"):
        ProductionLiveProviderExecutionResult(
            **{
                **_fake_provider_execution_result(
                    ProductionLiveProviderExecutionRequest(
                        **_provider_execution_request_payload(invocation)
                    )
                ),
                "raw_provider_payload_embedded": True,
            }
        )


def test_live_provider_effect_receipt_intake_prepares_response_receipt() -> None:
    request_readiness, executor_readiness = _ready_live_provider_executor(
        gate_id="weather_gate"
    )
    invocation = evaluate_live_provider_executor_invocation_guard(
        executor_readiness,
        _provider_executor_invocation_payload(executor_readiness),
    )
    effect_receipt = ProductionLiveProviderEffectReceipt(
        **_provider_effect_receipt_payload(invocation)
    )

    effect_intake = build_provider_response_receipt_from_provider_effect_receipt(
        invocation,
        effect_receipt,
    )
    response_receipt = effect_intake.response_receipt
    response_intake = build_live_observation_from_provider_response_receipt(
        request_readiness,
        response_receipt or {},
        provider_executor_invocation=invocation,
    )
    event = build_production_weather_gate_event(
        response_intake.weather_observation or {}
    )

    assert effect_intake.status == "provider_response_receipt_prepared"
    assert effect_intake.response_receipt_prepared is True
    assert effect_intake.provider_executor_invocation_authorized is True
    assert effect_intake.provider_effect_lineage_match is True
    assert effect_intake.provider_effect_evidence_present is True
    assert effect_intake.provider_effect_successful is True
    assert effect_intake.response_receipt_sha256 is not None
    assert response_receipt is not None
    assert response_receipt.provider_executor_invocation_sha256 == invocation.sha256
    assert response_receipt.provider_execution_ref == invocation.provider_execution_ref
    assert response_receipt.provider_execution_sha256 == (
        invocation.provider_execution_sha256
    )
    assert response_receipt.executor_reported_provider_network_request_performed is True
    assert response_receipt.executor_reported_real_provider_api_called is True
    assert effect_intake.provider_network_request_performed_by_intake is False
    assert effect_intake.real_provider_api_called_by_intake is False
    assert effect_intake.runtime_ingest_performed_by_intake is False
    assert effect_intake.safety_api_called is False
    assert effect_intake.phase1_l0_l4_state_mutated is False
    assert response_intake.status == "live_observation_prepared"
    assert response_intake.provider_executor_invocation_authorized is True
    assert invocation.provider_execution_ref in event.evidence_refs
    assert event.data_quality.live_network_calls_made is False
    assert event.boundary.safety_api_called is False


def test_live_provider_effect_receipt_intake_fails_closed() -> None:
    _, executor_readiness = _ready_live_provider_executor(gate_id="weather_gate")
    invocation = evaluate_live_provider_executor_invocation_guard(
        executor_readiness,
        _provider_executor_invocation_payload(executor_readiness),
    )
    base_receipt = _provider_effect_receipt_payload(invocation)
    blocked_invocation = invocation.model_copy(
        update={
            "status": "blocked_provider_operator_identity_missing",
            "provider_executor_invocation_authorized": False,
            "operator_identity_present": False,
        }
    )

    not_authorized = build_provider_response_receipt_from_provider_effect_receipt(
        blocked_invocation,
        base_receipt,
    )
    mismatch = build_provider_response_receipt_from_provider_effect_receipt(
        invocation,
        {**base_receipt, "connector_id": "connector.cwa.other"},
    )
    missing_evidence = build_provider_response_receipt_from_provider_effect_receipt(
        invocation,
        {**base_receipt, "provider_evidence_ref": None},
    )
    failed_provider = build_provider_response_receipt_from_provider_effect_receipt(
        invocation,
        {**base_receipt, "response_status": "failed"},
    )
    no_executor_effect = build_provider_response_receipt_from_provider_effect_receipt(
        invocation,
        {
            **base_receipt,
            "executor_reported_provider_network_request_performed": False,
        },
    )

    assert not_authorized.status == (
        "blocked_provider_executor_invocation_not_authorized"
    )
    assert not_authorized.response_receipt is None
    assert mismatch.status == "blocked_provider_effect_lineage_mismatch"
    assert missing_evidence.status == "blocked_provider_effect_evidence_missing"
    assert failed_provider.status == "blocked_provider_effect_not_successful"
    assert no_executor_effect.status == "blocked_provider_effect_not_successful"
    assert no_executor_effect.provider_network_request_performed_by_intake is False
    assert no_executor_effect.safety_api_called is False
    with pytest.raises(ValueError, match="cannot perform effects"):
        ProductionLiveProviderEffectReceiptIntakeBoundary(
            real_provider_api_called_by_intake=True
        )
    with pytest.raises(ValueError, match="cannot embed raw payloads"):
        ProductionLiveProviderEffectReceipt(
            **{**base_receipt, "raw_provider_payload_embedded": True}
        )


def test_live_provider_request_contract_authorizes_boundary_without_provider_call() -> None:
    health_sha = aggregate_sha256(
        [{"connector": "cwa-weather", "health": "healthy", "checked": "attested"}]
    )
    boundary_sha = aggregate_sha256(
        [{"boundary": "cwa-weather-provider-effect", "review": "approved"}]
    )
    manifest = ProductionLiveProviderConnectorManifest(
        gate_id="weather_gate",
        connector_id="connector.cwa.weather",
        provider_name="Central Weather Administration",
        source_provider="cwa_weather_fusion_live",
        source_path="provider://cwa/weather/chilai-nanhua/latest",
        provider_dataset_ids=["F-C0041-001"],
        route_scope_ref="runtime://route/chilai-nanhua/segment/seg.001",
        health_status="healthy",
        connector_health_ref="attestation://connector/cwa-weather/healthy",
        connector_health_sha256=health_sha,
        credential_ref="secret://scout/cwa/opendata-api-token",
    )
    request = ProductionLiveProviderRequestContract(
        gate_id="weather_gate",
        connector_id="connector.cwa.weather",
        source_provider="cwa_weather_fusion_live",
        source_path="provider://cwa/weather/chilai-nanhua/latest",
        route_scope_ref="runtime://route/chilai-nanhua/segment/seg.001",
        connector_health_ref="attestation://connector/cwa-weather/healthy",
        connector_health_sha256=health_sha,
        credential_ref="secret://scout/cwa/opendata-api-token",
        idempotency_key="weather-request-D1-seg001",
        execution_mode="provider_effect_boundary_request",
        reviewed_provider_effect_boundary_ref=(
            "attestation://provider-effect/cwa-weather/reviewed"
        ),
        reviewed_provider_effect_boundary_sha256=boundary_sha,
    )

    receipt = evaluate_production_live_provider_request_contract(manifest, request)
    weather_event = build_production_weather_gate_event(
        {
            "source_provider": "cwa_weather_fusion_live",
            "source_path": "provider://cwa/weather/chilai-nanhua/latest",
            "event_id": "weather_gate:live-cwa-heavy-rain",
            "warning_level": "unsafe",
            "warning_type": "heavy_rain",
            "rain_risk": True,
            "source_age_minutes": 20,
            "provider_dataset_ids": ["F-C0041-001"],
            "provider_evidence_ref": "cwa://opendata/F-C0041-001/fresh-qpf",
            "provider_request_ref": receipt.provider_request_ref,
            "provider_request_sha256": receipt.provider_request_sha256,
            "freshness_attestation_ref": "attestation://freshness/weather/under-180m",
            "route_scope_ref": "runtime://route/chilai-nanhua/segment/seg.001",
            "route_context": {
                "route_id": "runtime.route.chilai-nanhua",
                "segment_id": "seg.001",
            },
        }
    )
    serialized = json.dumps(
        {
            "receipt": receipt.model_dump(mode="json"),
            "event": weather_event.model_dump(mode="json"),
        },
        sort_keys=True,
    )

    assert receipt.status == "provider_request_boundary_authorized"
    assert receipt.request_contract_prepared is True
    assert receipt.provider_request_boundary_authorized is True
    assert receipt.provider_request_ref is not None
    assert receipt.provider_request_sha256 is not None
    assert receipt.provider_network_request_performed is False
    assert receipt.real_provider_api_called is False
    assert receipt.connector_health_checked_by_guard is False
    assert receipt.runtime_ingest_performed is False
    assert receipt.safety_api_called is False
    assert receipt.phase1_l0_l4_state_mutated is False
    assert receipt.credential_material_embedded is False
    assert receipt.provider_request_ref in weather_event.evidence_refs
    assert weather_event.data_quality.live_network_calls_made is False
    assert "/safety/" not in serialized
    assert "raw_payload" not in serialized


def test_live_provider_request_contract_fails_closed_before_provider_effect_boundary() -> None:
    health_sha = aggregate_sha256([{"connector": "cwa-weather", "health": "healthy"}])
    manifest = ProductionLiveProviderConnectorManifest(
        gate_id="weather_gate",
        connector_id="connector.cwa.weather",
        provider_name="Central Weather Administration",
        source_provider="cwa_weather_fusion_live",
        source_path="provider://cwa/weather/chilai-nanhua/latest",
        provider_dataset_ids=["F-C0041-001"],
        route_scope_ref="runtime://route/chilai-nanhua/segment/seg.001",
        health_status="healthy",
        connector_health_ref="attestation://connector/cwa-weather/healthy",
        connector_health_sha256=health_sha,
        credential_ref="secret://scout/cwa/opendata-api-token",
    )
    base_request = {
        "gate_id": "weather_gate",
        "connector_id": "connector.cwa.weather",
        "source_provider": "cwa_weather_fusion_live",
        "source_path": "provider://cwa/weather/chilai-nanhua/latest",
        "route_scope_ref": "runtime://route/chilai-nanhua/segment/seg.001",
        "connector_health_ref": "attestation://connector/cwa-weather/healthy",
        "connector_health_sha256": health_sha,
        "credential_ref": "secret://scout/cwa/opendata-api-token",
        "idempotency_key": "weather-request-D1-seg001",
    }

    dry_run = evaluate_production_live_provider_request_contract(
        manifest,
        ProductionLiveProviderRequestContract(**base_request),
    )
    missing_boundary = evaluate_production_live_provider_request_contract(
        manifest,
        ProductionLiveProviderRequestContract(
            **base_request,
            execution_mode="provider_effect_boundary_request",
        ),
    )
    degraded_manifest = manifest.model_copy(update={"health_status": "degraded"})
    degraded_health = evaluate_production_live_provider_request_contract(
        degraded_manifest,
        ProductionLiveProviderRequestContract(**base_request),
    )
    missing_secret_manifest = manifest.model_copy(update={"credential_ref": None})
    missing_secret = evaluate_production_live_provider_request_contract(
        missing_secret_manifest,
        ProductionLiveProviderRequestContract(
            **{**base_request, "credential_ref": None}
        ),
    )
    mismatch = evaluate_production_live_provider_request_contract(
        manifest,
        ProductionLiveProviderRequestContract(
            **{**base_request, "route_scope_ref": "runtime://route/other/seg.002"}
        ),
    )

    assert dry_run.status == "dry_run_ready"
    assert dry_run.provider_request_boundary_authorized is False
    assert dry_run.provider_request_ref is None
    assert missing_boundary.status == "blocked_provider_effect_boundary_missing"
    assert degraded_health.status == "blocked_connector_health_not_ready"
    assert missing_secret.status == "blocked_requires_credential_ref"
    assert mismatch.status == "blocked_provider_request_lineage_mismatch"
    with pytest.raises(ValueError, match="cannot perform effects"):
        ProductionLiveProviderRequestContract(
            **base_request,
            request_network_call_performed=True,
        )


def _provider_response_receipt_payload(readiness, *, gate_id: str = "weather_gate"):
    base = {
        "source_provider": (
            "cwa_weather_fusion_live"
            if gate_id == "weather_gate"
            else "cwa_environment_threat_live"
        ),
        "source_path": (
            "provider://cwa/weather/chilai-nanhua/latest/response-001"
            if gate_id == "weather_gate"
            else "provider://cwa/environment-threat/chilai-nanhua/current/response-001"
        ),
        "gate_id": gate_id,
        "connector_id": readiness.connector_id,
        "provider_request_readiness_sha256": readiness.sha256,
        "manifest_sha256": readiness.manifest_sha256,
        "request_contract_sha256": readiness.request_contract_sha256,
        "source_observation_path": readiness.source_observation_path,
        "route_scope_ref": readiness.route_scope_ref,
        "provider_request_ref": readiness.provider_request_ref,
        "provider_request_sha256": readiness.provider_request_sha256,
        "provider_dataset_ids": ["F-C0041-001"],
        "provider_evidence_ref": (
            "cwa://opendata/F-C0041-001/weather-response-001"
            if gate_id == "weather_gate"
            else "cwa://opendata/F-C0041-001/threat-response-001"
        ),
        "provider_evidence_sha256": "a" * 64,
        "freshness_attestation_ref": (
            "attestation://freshness/weather/under-180m"
            if gate_id == "weather_gate"
            else "attestation://freshness/environment-threat/current"
        ),
        "freshness_attestation_sha256": "b" * 64,
        "source_age_minutes": 18,
        "freshness_requirement_minutes": readiness.freshness_requirement_minutes,
        "response_status": "success",
        "observed_at_offset_s": 480,
        "route_context": {
            "route_id": "runtime.route.chilai-nanhua",
            "segment_id": "seg.001",
            "checkpoint_id": "cp.001",
        },
        "executor_reported_provider_network_request_performed": True,
        "executor_reported_real_provider_api_called": True,
    }
    if gate_id == "weather_gate":
        return {
            **base,
            "warning_level": "unsafe",
            "warning_type": "heavy_rain",
            "rain_risk": True,
        }
    return {
        **base,
        "threat_type": "washout",
        "passability": "blocked",
        "immediacy": "nearby",
        "route_blocked": True,
        "current_observation_ref": "device://camera/summary/route-blocked",
        "field_attestation_ref": "operator://leader/report/route-blocked-reviewed",
    }


def test_live_provider_response_receipt_intake_prepares_weather_observation() -> None:
    readiness = _authorized_live_provider_request(gate_id="weather_gate")
    receipt = ProductionLiveProviderResponseReceipt(
        **_provider_response_receipt_payload(readiness, gate_id="weather_gate")
    )

    intake = build_live_observation_from_provider_response_receipt(
        readiness,
        receipt,
    )
    event = build_production_weather_gate_event(intake.weather_observation or {})
    audit = build_production_live_evidence_contract_audit([event])
    serialized = json.dumps(
        {
            "intake": intake.model_dump(mode="json"),
            "event": event.model_dump(mode="json"),
        },
        sort_keys=True,
    )

    assert intake.status == "live_observation_prepared"
    assert intake.live_observation_prepared is True
    assert intake.weather_observation is not None
    assert intake.environment_threat_observation is None
    assert intake.provider_response_successful is True
    assert intake.provider_response_current is True
    assert intake.executor_reported_provider_network_request_performed is True
    assert intake.provider_network_request_performed_by_intake is False
    assert intake.real_provider_api_called_by_intake is False
    assert intake.runtime_ingest_performed_by_intake is False
    assert intake.safety_api_called is False
    assert intake.phase1_l0_l4_state_mutated is False
    assert intake.intake_verified_live_safety_truth is False
    assert readiness.provider_request_ref in event.evidence_refs
    assert event.gate_id == "weather_gate"
    assert event.severity == "retreat_review"
    assert event.data_quality.live_network_calls_made is False
    assert audit.rows[0].status == "live_contract_ready"
    assert audit.production_weather_environment_ready is False
    assert "/safety/" not in serialized
    assert "raw_payload" not in serialized


def test_live_provider_response_receipt_intake_prepares_threat_observation() -> None:
    readiness = _authorized_live_provider_request(gate_id="environment_threat_gate")
    receipt = ProductionLiveProviderResponseReceipt(
        **_provider_response_receipt_payload(
            readiness,
            gate_id="environment_threat_gate",
        )
    )

    intake = build_live_observation_from_provider_response_receipt(
        readiness,
        receipt,
    )
    event = build_production_environment_threat_gate_event(
        intake.environment_threat_observation or {}
    )

    assert intake.status == "live_observation_prepared"
    assert intake.environment_threat_observation is not None
    assert intake.weather_observation is None
    assert event.gate_id == "environment_threat_gate"
    assert event.severity == "retreat_review"
    assert event.boundary.safety_api_called is False
    assert event.boundary.phase1_l0_l4_state_mutated is False
    assert readiness.provider_request_ref in event.evidence_refs


def _freshness_attestor_invocation_payload(
    response_receipt: ProductionLiveProviderResponseReceipt,
) -> dict[str, object]:
    return {
        "source_provider": "resident_freshness_checker",
        "source_path": "attestation://freshness/weather/invocation",
        "gate_id": response_receipt.gate_id,
        "source_observation_path": response_receipt.source_observation_path,
        "route_scope_ref": response_receipt.route_scope_ref,
        "provider_request_ref": response_receipt.provider_request_ref,
        "provider_evidence_ref": response_receipt.provider_evidence_ref,
        "provider_evidence_sha256": response_receipt.provider_evidence_sha256,
        "freshness_requirement_minutes": (
            response_receipt.freshness_requirement_minutes
        ),
        "reviewed_freshness_attestor_effect_boundary_ref": (
            "attestation://freshness/weather/effect-boundary"
        ),
        "reviewed_freshness_attestor_effect_boundary_sha256": "4" * 64,
        "fallback_plan_ref": "attestation://freshness/weather/fallback",
        "fallback_plan_sha256": "5" * 64,
        "operator_identity_ref": "operator://identity/incident-commander-01",
        "operator_identity_sha256": "6" * 64,
        "operator_role": "incident_commander",
        "explicit_confirmation": True,
        "confirmation_phrase": "INVOKE SCOUT FRESHNESS ATTESTOR",
        "idempotency_key": "freshness-attestor-invocation-001",
    }


def _freshness_attestation_receipt_payload(
    response_receipt: ProductionLiveProviderResponseReceipt | None = None,
) -> dict[str, object]:
    return {
        "source_provider": "resident_freshness_checker",
        "source_path": "attestation://freshness/weather/under-180m",
        "gate_id": "weather_gate",
        "source_observation_path": (
            None if response_receipt is None else response_receipt.source_observation_path
        ),
        "route_scope_ref": (
            "runtime://route/chilai-nanhua/segment/seg.001"
            if response_receipt is None
            else response_receipt.route_scope_ref
        ),
        "provider_request_ref": (
            None if response_receipt is None else response_receipt.provider_request_ref
        ),
        "provider_evidence_ref": (
            "cwa://opendata/F-C0041-001/weather-response-001"
            if response_receipt is None
            else response_receipt.provider_evidence_ref
        ),
        "provider_evidence_sha256": (
            "a" * 64 if response_receipt is None else response_receipt.provider_evidence_sha256
        ),
        "freshness_attestation_ref": "attestation://freshness/weather/under-180m",
        "freshness_attestation_sha256": "f" * 64,
        "source_age_minutes": 18,
        "freshness_requirement_minutes": (
            180
            if response_receipt is None
            else response_receipt.freshness_requirement_minutes
        ),
        "freshness_status": "current",
        "attested_current": True,
        "route_context": {
            "route_id": "runtime.route.chilai-nanhua",
            "segment_id": "seg.001",
            "checkpoint_id": "cp.001",
        },
        "executor_reported_freshness_check_performed": True,
    }


def test_live_freshness_attestor_invocation_guard_binds_freshness_intake() -> None:
    readiness = _authorized_live_provider_request(gate_id="weather_gate")
    response_payload = {
        **_provider_response_receipt_payload(readiness, gate_id="weather_gate"),
        "freshness_attestation_ref": None,
        "freshness_attestation_sha256": None,
    }
    response_receipt = ProductionLiveProviderResponseReceipt(**response_payload)
    invocation = evaluate_live_freshness_attestor_invocation_guard(
        ProductionLiveFreshnessAttestorInvocationRequest(
            **_freshness_attestor_invocation_payload(response_receipt)
        )
    )
    freshness_receipt = ProductionLiveFreshnessAttestationReceipt(
        **{
            **_freshness_attestation_receipt_payload(response_receipt),
            "freshness_attestor_invocation_sha256": invocation.sha256,
            "freshness_attestation_execution_ref": (
                invocation.freshness_attestation_execution_ref
            ),
            "freshness_attestation_execution_sha256": (
                invocation.freshness_attestation_execution_sha256
            ),
        }
    )

    freshness = build_live_freshness_attestation_intake(
        freshness_receipt,
        response_receipt,
        freshness_attestor_invocation=invocation,
    )
    intake = build_live_observation_from_provider_response_receipt(
        readiness,
        response_receipt,
        freshness_attestation=freshness,
    )

    assert invocation.status == "freshness_attestor_invocation_authorized"
    assert invocation.freshness_attestor_invocation_authorized is True
    assert invocation.freshness_attestor_effect_boundary_present is True
    assert invocation.freshness_attestor_input_evidence_present is True
    assert invocation.fallback_plan_present is True
    assert invocation.operator_identity_present is True
    assert invocation.explicit_confirmation_present is True
    assert invocation.freshness_attestation_execution_ref is not None
    assert invocation.freshness_attestation_execution_sha256 is not None
    assert invocation.freshness_check_performed_by_guard is False
    assert invocation.provider_network_request_performed_by_guard is False
    assert invocation.safety_api_called is False
    assert freshness.status == "freshness_attestation_prepared"
    assert freshness.freshness_attestor_invocation_sha256 == invocation.sha256
    assert freshness.freshness_attestation_execution_ref == (
        invocation.freshness_attestation_execution_ref
    )
    assert freshness.freshness_attestor_invocation_authorized is True
    assert freshness.freshness_attestor_invocation_lineage_match is True
    assert freshness.freshness_check_performed_by_intake is False
    assert freshness.safety_api_called is False
    assert intake.status == "live_observation_prepared"
    assert intake.freshness_attestation_ref == freshness.freshness_attestation_ref
    assert intake.weather_observation is not None


def test_live_freshness_attestor_invocation_guard_fails_closed() -> None:
    readiness = _authorized_live_provider_request(gate_id="weather_gate")
    response_receipt = ProductionLiveProviderResponseReceipt(
        **_provider_response_receipt_payload(readiness, gate_id="weather_gate")
    )
    base_request = _freshness_attestor_invocation_payload(response_receipt)
    authorized = evaluate_live_freshness_attestor_invocation_guard(base_request)
    base_receipt = {
        **_freshness_attestation_receipt_payload(response_receipt),
        "freshness_attestor_invocation_sha256": authorized.sha256,
        "freshness_attestation_execution_ref": (
            authorized.freshness_attestation_execution_ref
        ),
        "freshness_attestation_execution_sha256": (
            authorized.freshness_attestation_execution_sha256
        ),
    }

    missing_boundary = evaluate_live_freshness_attestor_invocation_guard(
        {
            **base_request,
            "reviewed_freshness_attestor_effect_boundary_ref": None,
            "reviewed_freshness_attestor_effect_boundary_sha256": None,
        }
    )
    missing_input = evaluate_live_freshness_attestor_invocation_guard(
        {
            **base_request,
            "provider_evidence_ref": None,
            "provider_evidence_sha256": None,
        }
    )
    missing_operator = evaluate_live_freshness_attestor_invocation_guard(
        {
            **base_request,
            "operator_identity_ref": None,
            "operator_identity_sha256": None,
        }
    )
    missing_confirmation = evaluate_live_freshness_attestor_invocation_guard(
        {**base_request, "confirmation_phrase": "CHECK FRESHNESS NOW"}
    )
    blocked_invocation = authorized.model_copy(
        update={
            "status": "blocked_freshness_attestor_operator_identity_missing",
            "freshness_attestor_invocation_authorized": False,
            "operator_identity_present": False,
        }
    )
    not_authorized = build_live_freshness_attestation_intake(
        base_receipt,
        response_receipt,
        freshness_attestor_invocation=blocked_invocation,
    )
    mismatch = build_live_freshness_attestation_intake(
        {
            **base_receipt,
            "route_scope_ref": "runtime://route/other/segment/seg.009",
        },
        response_receipt,
        freshness_attestor_invocation=authorized,
    )

    assert missing_boundary.status == (
        "blocked_freshness_attestor_effect_boundary_missing"
    )
    assert missing_input.status == "blocked_freshness_attestor_input_evidence_missing"
    assert missing_operator.status == "blocked_freshness_attestor_operator_identity_missing"
    assert missing_confirmation.status == (
        "blocked_explicit_freshness_attestor_confirmation_missing"
    )
    assert missing_confirmation.freshness_check_performed_by_guard is False
    assert not_authorized.status == (
        "blocked_freshness_attestor_invocation_not_authorized"
    )
    assert not_authorized.freshness_attestation_prepared is False
    assert mismatch.status == "blocked_freshness_attestor_invocation_lineage_mismatch"
    assert mismatch.safety_api_called is False
    with pytest.raises(ValueError, match="cannot perform effects"):
        ProductionLiveFreshnessAttestorInvocationBoundary(
            freshness_check_performed_by_guard=True
        )
    with pytest.raises(ValueError, match="cannot embed raw payloads"):
        ProductionLiveFreshnessAttestorInvocationRequest(
            **{**base_request, "raw_provider_payload_embedded": True}
        )


def _freshness_attestation_execution_request_payload(
    invocation: object,
) -> dict[str, object]:
    return {
        "gate_id": invocation.gate_id,
        "freshness_attestor_invocation_sha256": invocation.sha256,
        "freshness_attestor_invocation_request_sha256": (
            invocation.freshness_attestor_invocation_request_sha256
        ),
        "source_observation_path": invocation.source_observation_path,
        "route_scope_ref": invocation.route_scope_ref,
        "provider_request_ref": invocation.provider_request_ref,
        "provider_response_receipt_sha256": (
            invocation.provider_response_receipt_sha256
        ),
        "provider_evidence_ref": invocation.provider_evidence_ref,
        "provider_evidence_sha256": invocation.provider_evidence_sha256,
        "freshness_requirement_minutes": invocation.freshness_requirement_minutes,
        "freshness_attestation_execution_ref": (
            invocation.freshness_attestation_execution_ref
        ),
        "freshness_attestation_execution_sha256": (
            invocation.freshness_attestation_execution_sha256
        ),
        "reviewed_freshness_attestor_effect_boundary_ref": (
            invocation.reviewed_freshness_attestor_effect_boundary_ref
        ),
        "reviewed_freshness_attestor_effect_boundary_sha256": (
            invocation.reviewed_freshness_attestor_effect_boundary_sha256
        ),
        "fallback_plan_ref": invocation.fallback_plan_ref,
        "fallback_plan_sha256": invocation.fallback_plan_sha256,
        "operator_identity_ref": invocation.operator_identity_ref,
        "operator_identity_sha256": invocation.operator_identity_sha256,
        "operator_role": invocation.operator_role,
        "idempotency_key": invocation.idempotency_key,
    }


def _fake_freshness_attestation_execution_result(
    request: ProductionLiveFreshnessAttestationExecutionRequest,
) -> dict[str, object]:
    payload = request.model_dump(mode="json")
    assert "credential_ref" not in payload
    return {
        "source_provider": "freshness_currentness_live",
        "source_path": "attestation://freshness/weather/execution-result-001",
        "gate_id": request.gate_id,
        "source_observation_path": request.source_observation_path,
        "route_scope_ref": request.route_scope_ref,
        "provider_request_ref": request.provider_request_ref,
        "provider_response_receipt_sha256": (
            request.provider_response_receipt_sha256
        ),
        "provider_evidence_ref": request.provider_evidence_ref,
        "provider_evidence_sha256": request.provider_evidence_sha256,
        "freshness_attestation_ref": "attestation://freshness/weather/executed-current",
        "freshness_attestation_sha256": "a" * 64,
        "source_age_minutes": 12,
        "freshness_requirement_minutes": request.freshness_requirement_minutes,
        "freshness_status": "current",
        "attested_current": True,
        "route_context": {
            "route_id": "runtime.route.chilai-nanhua",
            "segment_id": "seg.001",
            "checkpoint_id": "cp.001",
        },
        "executor_reported_freshness_check_performed": True,
    }


def test_live_freshness_attestor_executor_harness_emits_freshness_receipt() -> None:
    readiness = _authorized_live_provider_request(gate_id="weather_gate")
    response_receipt = ProductionLiveProviderResponseReceipt(
        **_provider_response_receipt_payload(readiness, gate_id="weather_gate")
    )
    invocation = evaluate_live_freshness_attestor_invocation_guard(
        _freshness_attestor_invocation_payload(response_receipt)
    )
    seen_requests: list[ProductionLiveFreshnessAttestationExecutionRequest] = []

    def freshness_client(
        request: ProductionLiveFreshnessAttestationExecutionRequest,
    ) -> dict[str, object]:
        seen_requests.append(request)
        return _fake_freshness_attestation_execution_result(request)

    execution = execute_live_freshness_attestation_check_with_client(
        invocation,
        freshness_client,
    )
    freshness = build_live_freshness_attestation_intake(
        execution.freshness_receipt or {},
        response_receipt,
        freshness_attestor_invocation=invocation,
    )
    intake = build_live_observation_from_provider_response_receipt(
        readiness,
        response_receipt,
        freshness_attestation=freshness,
    )

    assert execution.status == "freshness_attestation_receipt_emitted"
    assert execution.freshness_attestor_invocation_authorized is True
    assert execution.freshness_attestation_client_called is True
    assert execution.freshness_attestation_client_result_valid is True
    assert execution.freshness_attestation_client_effect_present is True
    assert execution.freshness_receipt is not None
    assert execution.freshness_receipt_sha256 is not None
    assert execution.provider_network_request_performed_by_executor is False
    assert execution.runtime_ingest_performed_by_executor is False
    assert execution.safety_api_called is False
    assert execution.phase1_l0_l4_state_mutated is False
    assert execution.outbound_transport_invoked is False
    assert execution.hardware_control_performed is False
    assert len(seen_requests) == 1
    assert seen_requests[0].freshness_attestor_invocation_sha256 == (
        invocation.sha256
    )
    assert seen_requests[0].provider_evidence_ref == invocation.provider_evidence_ref
    assert seen_requests[0].safety_api_called is False
    assert freshness.status == "freshness_attestation_prepared"
    assert freshness.freshness_attestor_invocation_lineage_match is True
    assert intake.status == "live_observation_prepared"


def test_live_freshness_attestor_executor_harness_fails_closed() -> None:
    readiness = _authorized_live_provider_request(gate_id="weather_gate")
    response_receipt = ProductionLiveProviderResponseReceipt(
        **_provider_response_receipt_payload(readiness, gate_id="weather_gate")
    )
    invocation = evaluate_live_freshness_attestor_invocation_guard(
        _freshness_attestor_invocation_payload(response_receipt)
    )
    calls: list[ProductionLiveFreshnessAttestationExecutionRequest] = []

    def freshness_client(
        request: ProductionLiveFreshnessAttestationExecutionRequest,
    ) -> dict[str, object]:
        calls.append(request)
        return _fake_freshness_attestation_execution_result(request)

    blocked_invocation = invocation.model_copy(
        update={
            "status": "blocked_freshness_attestor_operator_identity_missing",
            "freshness_attestor_invocation_authorized": False,
            "operator_identity_present": False,
        }
    )
    not_authorized = execute_live_freshness_attestation_check_with_client(
        blocked_invocation,
        freshness_client,
    )
    invalid_result = execute_live_freshness_attestation_check_with_client(
        invocation,
        lambda request: {
            **_fake_freshness_attestation_execution_result(request),
            "raw_provider_payload_embedded": True,
        },
    )
    missing_effect = execute_live_freshness_attestation_check_with_client(
        invocation,
        lambda request: {
            **_fake_freshness_attestation_execution_result(request),
            "executor_reported_freshness_check_performed": False,
        },
    )

    assert not_authorized.status == (
        "blocked_freshness_attestor_invocation_not_authorized"
    )
    assert not_authorized.freshness_attestation_client_called is False
    assert invalid_result.status == "blocked_freshness_client_result_invalid"
    assert invalid_result.freshness_receipt is None
    assert missing_effect.status == "blocked_freshness_client_effect_missing"
    assert missing_effect.freshness_receipt is None
    assert missing_effect.safety_api_called is False
    assert calls == []
    with pytest.raises(ValueError, match="cannot perform runtime effects"):
        ProductionLiveFreshnessAttestationExecutionBoundary(safety_api_called=True)
    with pytest.raises(ValueError, match="cannot embed raw payloads"):
        ProductionLiveFreshnessAttestationExecutionResult(
            **{
                **_fake_freshness_attestation_execution_result(
                    ProductionLiveFreshnessAttestationExecutionRequest(
                        **_freshness_attestation_execution_request_payload(
                            invocation
                        )
                    )
                ),
                "raw_provider_payload_embedded": True,
            }
        )


def test_live_freshness_attestation_intake_enriches_provider_response() -> None:
    readiness = _authorized_live_provider_request(gate_id="weather_gate")
    response_payload = _provider_response_receipt_payload(
        readiness,
        gate_id="weather_gate",
    )
    response_payload_without_freshness = {
        **response_payload,
        "freshness_attestation_ref": None,
        "freshness_attestation_sha256": None,
    }
    response_receipt = ProductionLiveProviderResponseReceipt(
        **response_payload_without_freshness
    )
    freshness_receipt = ProductionLiveFreshnessAttestationReceipt(
        **_freshness_attestation_receipt_payload(response_receipt)
    )

    freshness = build_live_freshness_attestation_intake(
        freshness_receipt,
        response_receipt,
    )
    intake = build_live_observation_from_provider_response_receipt(
        readiness,
        response_receipt,
        freshness_attestation=freshness,
    )
    event = build_production_weather_gate_event(intake.weather_observation or {})

    assert freshness.status == "freshness_attestation_prepared"
    assert freshness.freshness_attestation_prepared is True
    assert freshness.freshness_check_performed is True
    assert freshness.freshness_evidence_present is True
    assert freshness.freshness_attestation_current is True
    assert freshness.freshness_check_performed_by_intake is False
    assert freshness.provider_network_request_performed_by_intake is False
    assert freshness.real_provider_api_called_by_intake is False
    assert freshness.runtime_ingest_performed_by_intake is False
    assert freshness.safety_api_called is False
    assert intake.status == "live_observation_prepared"
    assert intake.freshness_attestation_ref == freshness.freshness_attestation_ref
    assert intake.freshness_attestation_sha256 == (
        freshness.freshness_attestation_sha256
    )
    assert freshness.freshness_attestation_ref in event.evidence_refs
    assert event.data_quality.stale_signal_names == []
    assert event.boundary.safety_api_called is False
    assert event.boundary.phase1_l0_l4_state_mutated is False


def test_live_freshness_attestation_intake_fails_closed() -> None:
    readiness = _authorized_live_provider_request(gate_id="weather_gate")
    response_receipt = ProductionLiveProviderResponseReceipt(
        **_provider_response_receipt_payload(readiness, gate_id="weather_gate")
    )
    base_receipt = _freshness_attestation_receipt_payload(response_receipt)

    missing_performed = build_live_freshness_attestation_intake(
        {**base_receipt, "executor_reported_freshness_check_performed": False},
        response_receipt,
    )
    missing_evidence = build_live_freshness_attestation_intake(
        {**base_receipt, "freshness_attestation_ref": None},
        response_receipt,
    )
    stale = build_live_freshness_attestation_intake(
        {
            **base_receipt,
            "freshness_status": "stale",
            "attested_current": False,
            "source_age_minutes": 240,
        },
        response_receipt,
    )
    mismatch = build_live_freshness_attestation_intake(
        {**base_receipt, "route_scope_ref": "runtime://route/other/segment/seg.009"},
        response_receipt,
    )
    unready_intake = build_live_observation_from_provider_response_receipt(
        readiness,
        response_receipt,
        freshness_attestation=stale,
    )
    mismatched_ready = build_live_freshness_attestation_intake(
        {
            **_freshness_attestation_receipt_payload(),
            "route_scope_ref": "runtime://route/other/segment/seg.009",
        },
    )
    mismatched_response_intake = build_live_observation_from_provider_response_receipt(
        readiness,
        response_receipt,
        freshness_attestation=mismatched_ready,
    )

    assert missing_performed.status == "blocked_freshness_attestation_evidence_missing"
    assert missing_performed.freshness_attestation_prepared is False
    assert missing_evidence.status == "blocked_freshness_attestation_evidence_missing"
    assert stale.status == "blocked_freshness_attestation_not_current"
    assert mismatch.status == "blocked_freshness_attestation_lineage_mismatch"
    assert unready_intake.status == "blocked_freshness_attestation_not_ready"
    assert unready_intake.weather_observation is None
    assert mismatched_response_intake.status == (
        "blocked_freshness_attestation_lineage_mismatch"
    )
    with pytest.raises(ValueError, match="cannot perform effects"):
        ProductionLiveFreshnessAttestationBoundary(
            freshness_check_performed_by_intake=True
        )
    with pytest.raises(ValueError, match="cannot embed raw payloads"):
        ProductionLiveFreshnessAttestationReceipt(
            **{**base_receipt, "raw_provider_payload_embedded": True}
        )


def _provider_response_receipt_sha256_for_test(
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


def _field_device_validator_invocation_payload(
    response_receipt: ProductionLiveProviderResponseReceipt,
) -> dict[str, object]:
    return {
        "source_provider": "field_device_validation_live",
        "source_path": "field://validation/weather/invocation",
        "gate_id": response_receipt.gate_id,
        "source_observation_path": response_receipt.source_observation_path,
        "route_scope_ref": response_receipt.route_scope_ref,
        "provider_request_ref": response_receipt.provider_request_ref,
        "provider_response_receipt_sha256": (
            _provider_response_receipt_sha256_for_test(response_receipt)
        ),
        "current_observation_ref": "field://validation/weather/current-observation",
        "device_evidence_ref": "device://camera/weather/sky-condition",
        "device_evidence_sha256": "d" * 64,
        "reviewed_field_device_validator_effect_boundary_ref": (
            "attestation://field-device/weather/effect-boundary"
        ),
        "reviewed_field_device_validator_effect_boundary_sha256": "7" * 64,
        "fallback_plan_ref": "attestation://field-device/weather/fallback",
        "fallback_plan_sha256": "8" * 64,
        "operator_identity_ref": "operator://identity/incident-commander-01",
        "operator_identity_sha256": "9" * 64,
        "operator_role": "incident_commander",
        "explicit_confirmation": True,
        "confirmation_phrase": "INVOKE SCOUT FIELD DEVICE VALIDATOR",
        "idempotency_key": "field-device-validator-invocation-001",
    }


def _field_device_validation_receipt_payload(
    response_receipt: ProductionLiveProviderResponseReceipt | None = None,
) -> dict[str, object]:
    return {
        "source_provider": "field_device_validation_live",
        "source_path": "field://validation/weather/leader-attested",
        "gate_id": "weather_gate",
        "source_observation_path": (
            None if response_receipt is None else response_receipt.source_observation_path
        ),
        "route_scope_ref": (
            "runtime://route/chilai-nanhua/segment/seg.001"
            if response_receipt is None
            else response_receipt.route_scope_ref
        ),
        "provider_request_ref": (
            None if response_receipt is None else response_receipt.provider_request_ref
        ),
        "provider_response_receipt_sha256": (
            None
            if response_receipt is None
            else _provider_response_receipt_sha256_for_test(response_receipt)
        ),
        "current_observation_ref": "field://validation/weather/current-observation",
        "field_attestation_ref": "field://validation/weather/leader-attested",
        "field_attestation_sha256": "c" * 64,
        "device_evidence_ref": "device://camera/weather/sky-condition",
        "device_evidence_sha256": "d" * 64,
        "operator_review_ref": "operator://leader/review/weather-field-validation",
        "operator_review_sha256": "e" * 64,
        "validation_status": "confirmed",
        "validation_age_minutes": 8,
        "max_validation_age_minutes": 180,
        "route_context": {
            "route_id": "runtime.route.chilai-nanhua",
            "segment_id": "seg.001",
            "checkpoint_id": "cp.001",
        },
        "executor_reported_field_device_validation_performed": True,
    }


def test_live_field_device_validator_invocation_guard_binds_validation_intake() -> None:
    readiness = _authorized_live_provider_request(gate_id="weather_gate")
    response_receipt = ProductionLiveProviderResponseReceipt(
        **_provider_response_receipt_payload(readiness, gate_id="weather_gate")
    )
    invocation = evaluate_live_field_device_validator_invocation_guard(
        ProductionLiveFieldDeviceValidatorInvocationRequest(
            **_field_device_validator_invocation_payload(response_receipt)
        )
    )
    validation_receipt = ProductionLiveFieldDeviceValidationReceipt(
        **{
            **_field_device_validation_receipt_payload(response_receipt),
            "field_device_validator_invocation_sha256": invocation.sha256,
            "field_device_validation_execution_ref": (
                invocation.field_device_validation_execution_ref
            ),
            "field_device_validation_execution_sha256": (
                invocation.field_device_validation_execution_sha256
            ),
        }
    )

    validation = build_live_field_device_validation_intake(
        validation_receipt,
        response_receipt,
        field_device_validator_invocation=invocation,
    )
    intake = build_live_observation_from_provider_response_receipt(
        readiness,
        response_receipt,
        field_validation=validation,
    )

    assert invocation.status == "field_device_validator_invocation_authorized"
    assert invocation.field_device_validator_invocation_authorized is True
    assert invocation.field_device_validator_effect_boundary_present is True
    assert invocation.field_device_validator_input_evidence_present is True
    assert invocation.fallback_plan_present is True
    assert invocation.operator_identity_present is True
    assert invocation.explicit_confirmation_present is True
    assert invocation.field_device_validation_execution_ref is not None
    assert invocation.field_device_validation_execution_sha256 is not None
    assert invocation.field_device_validation_performed_by_guard is False
    assert invocation.provider_network_request_performed_by_guard is False
    assert invocation.safety_api_called is False
    assert validation.status == "field_device_validation_prepared"
    assert validation.field_device_validator_invocation_sha256 == invocation.sha256
    assert validation.field_device_validation_execution_ref == (
        invocation.field_device_validation_execution_ref
    )
    assert validation.field_device_validator_invocation_authorized is True
    assert validation.field_device_validator_invocation_lineage_match is True
    assert validation.field_device_validation_performed_by_intake is False
    assert validation.safety_api_called is False
    assert intake.status == "live_observation_prepared"
    assert intake.field_attestation_ref == validation.field_attestation_ref
    assert intake.weather_observation is not None


def test_live_field_device_validator_invocation_guard_fails_closed() -> None:
    readiness = _authorized_live_provider_request(gate_id="weather_gate")
    response_receipt = ProductionLiveProviderResponseReceipt(
        **_provider_response_receipt_payload(readiness, gate_id="weather_gate")
    )
    base_request = _field_device_validator_invocation_payload(response_receipt)
    authorized = evaluate_live_field_device_validator_invocation_guard(base_request)
    base_receipt = {
        **_field_device_validation_receipt_payload(response_receipt),
        "field_device_validator_invocation_sha256": authorized.sha256,
        "field_device_validation_execution_ref": (
            authorized.field_device_validation_execution_ref
        ),
        "field_device_validation_execution_sha256": (
            authorized.field_device_validation_execution_sha256
        ),
    }

    missing_boundary = evaluate_live_field_device_validator_invocation_guard(
        {
            **base_request,
            "reviewed_field_device_validator_effect_boundary_ref": None,
            "reviewed_field_device_validator_effect_boundary_sha256": None,
        }
    )
    missing_input = evaluate_live_field_device_validator_invocation_guard(
        {
            **base_request,
            "current_observation_ref": None,
            "device_evidence_ref": None,
            "device_evidence_sha256": None,
        }
    )
    missing_operator = evaluate_live_field_device_validator_invocation_guard(
        {
            **base_request,
            "operator_identity_ref": None,
            "operator_identity_sha256": None,
        }
    )
    missing_confirmation = evaluate_live_field_device_validator_invocation_guard(
        {**base_request, "confirmation_phrase": "VALIDATE FIELD DEVICE NOW"}
    )
    blocked_invocation = authorized.model_copy(
        update={
            "status": "blocked_field_device_validator_operator_identity_missing",
            "field_device_validator_invocation_authorized": False,
            "operator_identity_present": False,
        }
    )
    not_authorized = build_live_field_device_validation_intake(
        base_receipt,
        response_receipt,
        field_device_validator_invocation=blocked_invocation,
    )
    mismatch = build_live_field_device_validation_intake(
        {
            **base_receipt,
            "route_scope_ref": "runtime://route/other/segment/seg.009",
        },
        response_receipt,
        field_device_validator_invocation=authorized,
    )

    assert missing_boundary.status == (
        "blocked_field_device_validator_effect_boundary_missing"
    )
    assert missing_input.status == "blocked_field_device_validator_input_evidence_missing"
    assert missing_operator.status == (
        "blocked_field_device_validator_operator_identity_missing"
    )
    assert missing_confirmation.status == (
        "blocked_explicit_field_device_validator_confirmation_missing"
    )
    assert missing_confirmation.field_device_validation_performed_by_guard is False
    assert not_authorized.status == (
        "blocked_field_device_validator_invocation_not_authorized"
    )
    assert not_authorized.field_device_validation_prepared is False
    assert mismatch.status == (
        "blocked_field_device_validator_invocation_lineage_mismatch"
    )
    assert mismatch.safety_api_called is False
    with pytest.raises(ValueError, match="cannot perform effects"):
        ProductionLiveFieldDeviceValidatorInvocationBoundary(
            field_device_validation_performed_by_guard=True
        )
    with pytest.raises(ValueError, match="cannot embed raw payloads"):
        ProductionLiveFieldDeviceValidatorInvocationRequest(
            **{**base_request, "raw_provider_payload_embedded": True}
        )


def _field_device_validation_execution_request_payload(
    invocation: object,
) -> dict[str, object]:
    return {
        "gate_id": invocation.gate_id,
        "field_device_validator_invocation_sha256": invocation.sha256,
        "field_device_validator_invocation_request_sha256": (
            invocation.field_device_validator_invocation_request_sha256
        ),
        "source_observation_path": invocation.source_observation_path,
        "route_scope_ref": invocation.route_scope_ref,
        "provider_request_ref": invocation.provider_request_ref,
        "provider_response_receipt_sha256": (
            invocation.provider_response_receipt_sha256
        ),
        "current_observation_ref": invocation.current_observation_ref,
        "device_evidence_ref": invocation.device_evidence_ref,
        "device_evidence_sha256": invocation.device_evidence_sha256,
        "field_device_validation_execution_ref": (
            invocation.field_device_validation_execution_ref
        ),
        "field_device_validation_execution_sha256": (
            invocation.field_device_validation_execution_sha256
        ),
        "reviewed_field_device_validator_effect_boundary_ref": (
            invocation.reviewed_field_device_validator_effect_boundary_ref
        ),
        "reviewed_field_device_validator_effect_boundary_sha256": (
            invocation.reviewed_field_device_validator_effect_boundary_sha256
        ),
        "fallback_plan_ref": invocation.fallback_plan_ref,
        "fallback_plan_sha256": invocation.fallback_plan_sha256,
        "operator_identity_ref": invocation.operator_identity_ref,
        "operator_identity_sha256": invocation.operator_identity_sha256,
        "operator_role": invocation.operator_role,
        "idempotency_key": invocation.idempotency_key,
    }


def _fake_field_device_validation_execution_result(
    request: ProductionLiveFieldDeviceValidationExecutionRequest,
) -> dict[str, object]:
    payload = request.model_dump(mode="json")
    assert "credential_ref" not in payload
    return {
        "source_provider": "field_device_validation_live",
        "source_path": "field://validation/weather/execution-result-001",
        "gate_id": request.gate_id,
        "source_observation_path": request.source_observation_path,
        "route_scope_ref": request.route_scope_ref,
        "provider_request_ref": request.provider_request_ref,
        "provider_response_receipt_sha256": (
            request.provider_response_receipt_sha256
        ),
        "current_observation_ref": request.current_observation_ref,
        "field_attestation_ref": "field://validation/weather/executed-confirmed",
        "field_attestation_sha256": "b" * 64,
        "device_evidence_ref": request.device_evidence_ref,
        "device_evidence_sha256": request.device_evidence_sha256,
        "operator_review_ref": "operator://leader/review/executed-field-validation",
        "operator_review_sha256": "c" * 64,
        "validation_status": "confirmed",
        "validation_age_minutes": 7,
        "max_validation_age_minutes": 180,
        "route_context": {
            "route_id": "runtime.route.chilai-nanhua",
            "segment_id": "seg.001",
            "checkpoint_id": "cp.001",
        },
        "executor_reported_field_device_validation_performed": True,
    }


def test_live_field_device_validator_executor_harness_emits_validation_receipt() -> None:
    readiness = _authorized_live_provider_request(gate_id="weather_gate")
    response_receipt = ProductionLiveProviderResponseReceipt(
        **_provider_response_receipt_payload(readiness, gate_id="weather_gate")
    )
    invocation = evaluate_live_field_device_validator_invocation_guard(
        _field_device_validator_invocation_payload(response_receipt)
    )
    seen_requests: list[ProductionLiveFieldDeviceValidationExecutionRequest] = []

    def field_device_client(
        request: ProductionLiveFieldDeviceValidationExecutionRequest,
    ) -> dict[str, object]:
        seen_requests.append(request)
        return _fake_field_device_validation_execution_result(request)

    execution = execute_live_field_device_validation_with_client(
        invocation,
        field_device_client,
    )
    validation = build_live_field_device_validation_intake(
        execution.validation_receipt or {},
        response_receipt,
        field_device_validator_invocation=invocation,
    )
    intake = build_live_observation_from_provider_response_receipt(
        readiness,
        response_receipt,
        field_validation=validation,
    )

    assert execution.status == "field_device_validation_receipt_emitted"
    assert execution.field_device_validator_invocation_authorized is True
    assert execution.field_device_validation_client_called is True
    assert execution.field_device_validation_client_result_valid is True
    assert execution.field_device_validation_client_effect_present is True
    assert execution.validation_receipt is not None
    assert execution.validation_receipt_sha256 is not None
    assert execution.provider_network_request_performed_by_executor is False
    assert execution.runtime_ingest_performed_by_executor is False
    assert execution.safety_api_called is False
    assert execution.phase1_l0_l4_state_mutated is False
    assert execution.outbound_transport_invoked is False
    assert execution.hardware_control_performed is False
    assert len(seen_requests) == 1
    assert seen_requests[0].field_device_validator_invocation_sha256 == (
        invocation.sha256
    )
    assert seen_requests[0].device_evidence_ref == invocation.device_evidence_ref
    assert seen_requests[0].safety_api_called is False
    assert validation.status == "field_device_validation_prepared"
    assert validation.field_device_validator_invocation_lineage_match is True
    assert intake.status == "live_observation_prepared"


def test_live_field_device_validator_executor_harness_fails_closed() -> None:
    readiness = _authorized_live_provider_request(gate_id="weather_gate")
    response_receipt = ProductionLiveProviderResponseReceipt(
        **_provider_response_receipt_payload(readiness, gate_id="weather_gate")
    )
    invocation = evaluate_live_field_device_validator_invocation_guard(
        _field_device_validator_invocation_payload(response_receipt)
    )
    calls: list[ProductionLiveFieldDeviceValidationExecutionRequest] = []

    def field_device_client(
        request: ProductionLiveFieldDeviceValidationExecutionRequest,
    ) -> dict[str, object]:
        calls.append(request)
        return _fake_field_device_validation_execution_result(request)

    blocked_invocation = invocation.model_copy(
        update={
            "status": "blocked_field_device_validator_operator_identity_missing",
            "field_device_validator_invocation_authorized": False,
            "operator_identity_present": False,
        }
    )
    not_authorized = execute_live_field_device_validation_with_client(
        blocked_invocation,
        field_device_client,
    )
    invalid_result = execute_live_field_device_validation_with_client(
        invocation,
        lambda request: {
            **_fake_field_device_validation_execution_result(request),
            "raw_provider_payload_embedded": True,
        },
    )
    missing_effect = execute_live_field_device_validation_with_client(
        invocation,
        lambda request: {
            **_fake_field_device_validation_execution_result(request),
            "executor_reported_field_device_validation_performed": False,
        },
    )

    assert not_authorized.status == (
        "blocked_field_device_validator_invocation_not_authorized"
    )
    assert not_authorized.field_device_validation_client_called is False
    assert invalid_result.status == "blocked_field_device_client_result_invalid"
    assert invalid_result.validation_receipt is None
    assert missing_effect.status == "blocked_field_device_client_effect_missing"
    assert missing_effect.validation_receipt is None
    assert missing_effect.safety_api_called is False
    assert calls == []
    with pytest.raises(ValueError, match="cannot perform runtime effects"):
        ProductionLiveFieldDeviceValidationExecutionBoundary(safety_api_called=True)
    with pytest.raises(ValueError, match="cannot embed raw payloads"):
        ProductionLiveFieldDeviceValidationExecutionResult(
            **{
                **_fake_field_device_validation_execution_result(
                    ProductionLiveFieldDeviceValidationExecutionRequest(
                        **_field_device_validation_execution_request_payload(
                            invocation
                        )
                    )
                ),
                "raw_provider_payload_embedded": True,
            }
        )


def test_live_field_device_validation_intake_enriches_provider_response() -> None:
    readiness = _authorized_live_provider_request(gate_id="weather_gate")
    response_receipt = ProductionLiveProviderResponseReceipt(
        **_provider_response_receipt_payload(readiness, gate_id="weather_gate")
    )
    validation_receipt = ProductionLiveFieldDeviceValidationReceipt(
        **_field_device_validation_receipt_payload(response_receipt)
    )

    validation = build_live_field_device_validation_intake(
        validation_receipt,
        response_receipt,
    )
    intake = build_live_observation_from_provider_response_receipt(
        readiness,
        response_receipt,
        field_validation=validation,
    )
    event = build_production_weather_gate_event(intake.weather_observation or {})
    residency = build_production_gate_residency_audit([event])
    residency_rows = {row.gate_id: row for row in residency.rows}

    assert validation.status == "field_device_validation_prepared"
    assert validation.field_device_validation_prepared is True
    assert validation.field_device_validation_performed is True
    assert validation.field_device_validation_evidence_present is True
    assert validation.field_device_validation_confirmed is True
    assert validation.field_device_validation_current is True
    assert validation.field_device_validation_performed_by_intake is False
    assert validation.provider_network_request_performed_by_intake is False
    assert validation.real_provider_api_called_by_intake is False
    assert validation.runtime_ingest_performed_by_intake is False
    assert validation.safety_api_called is False
    assert intake.status == "live_observation_prepared"
    assert intake.field_device_validation_present is True
    assert intake.field_device_validation_sha256 == validation.sha256
    assert intake.field_attestation_ref == validation.field_attestation_ref
    assert intake.device_evidence_ref == validation.device_evidence_ref
    assert validation.field_attestation_ref in event.evidence_refs
    assert validation.device_evidence_ref in event.evidence_refs
    assert residency_rows["weather_gate"].field_validation_present is True
    assert residency_rows["weather_gate"].status == "resident_ready"
    assert event.boundary.safety_api_called is False
    assert event.boundary.phase1_l0_l4_state_mutated is False


def test_live_field_device_validation_intake_fails_closed() -> None:
    readiness = _authorized_live_provider_request(gate_id="weather_gate")
    response_receipt = ProductionLiveProviderResponseReceipt(
        **_provider_response_receipt_payload(readiness, gate_id="weather_gate")
    )
    base_receipt = _field_device_validation_receipt_payload(response_receipt)

    missing_performed = build_live_field_device_validation_intake(
        {**base_receipt, "executor_reported_field_device_validation_performed": False},
        response_receipt,
    )
    missing_evidence = build_live_field_device_validation_intake(
        {**base_receipt, "field_attestation_ref": None},
        response_receipt,
    )
    disputed = build_live_field_device_validation_intake(
        {**base_receipt, "validation_status": "disputed"},
        response_receipt,
    )
    stale = build_live_field_device_validation_intake(
        {**base_receipt, "validation_age_minutes": 240},
        response_receipt,
    )
    mismatch = build_live_field_device_validation_intake(
        {**base_receipt, "route_scope_ref": "runtime://route/other/segment/seg.009"},
        response_receipt,
    )
    unready_intake = build_live_observation_from_provider_response_receipt(
        readiness,
        response_receipt,
        field_validation=disputed,
    )
    mismatched_ready_validation = build_live_field_device_validation_intake(
        {
            **_field_device_validation_receipt_payload(),
            "route_scope_ref": "runtime://route/other/segment/seg.009",
        },
    )
    mismatched_response_intake = build_live_observation_from_provider_response_receipt(
        readiness,
        response_receipt,
        field_validation=mismatched_ready_validation,
    )

    assert missing_performed.status == "blocked_field_device_validation_evidence_missing"
    assert missing_performed.field_device_validation_prepared is False
    assert missing_evidence.status == "blocked_field_device_validation_evidence_missing"
    assert disputed.status == "blocked_field_device_validation_not_confirmed"
    assert stale.status == "blocked_field_device_validation_not_current"
    assert mismatch.status == "blocked_field_device_validation_lineage_mismatch"
    assert unready_intake.status == "blocked_field_device_validation_not_ready"
    assert unready_intake.weather_observation is None
    assert mismatched_response_intake.status == (
        "blocked_field_device_validation_lineage_mismatch"
    )
    with pytest.raises(ValueError, match="cannot perform effects"):
        ProductionLiveFieldDeviceValidationBoundary(
            field_device_validation_performed_by_intake=True
        )
    with pytest.raises(ValueError, match="cannot embed raw payloads"):
        ProductionLiveFieldDeviceValidationReceipt(
            **{**base_receipt, "raw_location_payload_embedded": True}
        )


def test_live_provider_response_receipt_intake_fails_closed() -> None:
    readiness = _authorized_live_provider_request(gate_id="weather_gate")
    base_receipt = _provider_response_receipt_payload(readiness, gate_id="weather_gate")
    dry_run_readiness = readiness.model_copy(
        update={
            "status": "dry_run_ready",
            "provider_request_boundary_authorized": False,
            "provider_request_ref": None,
            "provider_request_sha256": None,
        }
    )

    unauthorized = build_live_observation_from_provider_response_receipt(
        dry_run_readiness,
        base_receipt,
    )
    mismatch = build_live_observation_from_provider_response_receipt(
        readiness,
        {**base_receipt, "provider_request_sha256": "wrong"},
    )
    missing_evidence = build_live_observation_from_provider_response_receipt(
        readiness,
        {**base_receipt, "provider_evidence_ref": None},
    )
    failed_response = build_live_observation_from_provider_response_receipt(
        readiness,
        {**base_receipt, "response_status": "failed"},
    )
    stale_response = build_live_observation_from_provider_response_receipt(
        readiness,
        {**base_receipt, "source_age_minutes": 240},
    )

    assert unauthorized.status == "blocked_provider_request_not_authorized"
    assert unauthorized.live_observation_prepared is False
    assert unauthorized.weather_observation is None
    assert mismatch.status == "blocked_provider_response_lineage_mismatch"
    assert missing_evidence.status == "blocked_missing_provider_evidence"
    assert failed_response.status == "blocked_provider_response_not_successful"
    assert stale_response.status == "blocked_provider_response_not_current"
    assert stale_response.runtime_ingest_performed_by_intake is False
    assert stale_response.safety_api_called is False
    with pytest.raises(ValueError, match="cannot perform effects"):
        ProductionLiveProviderResponseIntakeBoundary(
            real_provider_api_called_by_intake=True
        )
    with pytest.raises(ValueError, match="cannot embed raw payloads"):
        ProductionLiveProviderResponseReceipt(
            **{**base_receipt, "raw_provider_payload_embedded": True}
        )


def test_live_weather_bridge_blocks_unsafe_or_stale_sources() -> None:
    with pytest.raises(ValueError, match="fixture or inline source"):
        ProductionLiveWeatherObservation(
            source_provider="scout_runtime_fixture",
            source_path="inline:weather",
            warning_level="unsafe",
            source_age_minutes=20,
            provider_evidence_ref="cwa://opendata/F-C0041-001/fresh-qpf",
            freshness_attestation_ref="attestation://freshness/weather/under-180m",
            route_scope_ref="runtime://route/chilai-nanhua/segment/seg.001",
            route_context={
                "route_id": "runtime.route.chilai-nanhua",
                "segment_id": "seg.001",
            },
        )

    stale_event = build_production_weather_gate_event(
        {
            "source_provider": "cwa_weather_fusion_live",
            "source_path": "provider://cwa/weather/chilai-nanhua/latest",
            "warning_level": "severe",
            "warning_type": "thunderstorm",
            "lightning_risk": True,
            "source_age_minutes": 240,
            "provider_evidence_ref": "cwa://opendata/F-C0041-001/stale-qpf",
            "freshness_attestation_ref": "attestation://freshness/weather/stale",
            "route_scope_ref": "runtime://route/chilai-nanhua/segment/seg.001",
            "route_context": {
                "route_id": "runtime.route.chilai-nanhua",
                "segment_id": "seg.001",
            },
        }
    )
    threat_event = build_production_environment_threat_gate_event(
        {
            "source_provider": "field_environment_threat_live",
            "source_path": "resident://environment-threat/chilai-nanhua/current",
            "threat_type": "washout",
            "passability": "blocked",
            "immediacy": "nearby",
            "route_blocked": True,
            "current_observation_ref": "device://camera/summary/route-blocked",
            "freshness_attestation_ref": (
                "attestation://freshness/environment-threat/current"
            ),
            "route_scope_ref": "runtime://route/chilai-nanhua/segment/seg.001",
            "field_attestation_ref": "operator://leader/report/route-blocked",
            "route_context": {
                "route_id": "runtime.route.chilai-nanhua",
                "segment_id": "seg.001",
            },
        }
    )
    audit = build_production_live_evidence_contract_audit([stale_event, threat_event])
    by_id = {row.gate_id: row for row in audit.rows}

    assert stale_event.data_quality.stale_signal_names == ["weather_source"]
    assert audit.status == "partial_live_contracts"
    assert by_id["weather_gate"].status == "contract_gap"
    assert "freshness_contract_missing" in by_id["weather_gate"].blockers
    assert by_id["environment_threat_gate"].status == "live_contract_ready"
