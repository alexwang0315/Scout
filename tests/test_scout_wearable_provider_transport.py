import json
import subprocess
import sys
from pathlib import Path

from scout_wearable_provider_transport import (
    build_provider_live_transport_preflight,
    build_provider_live_transport_request_plan,
    write_provider_live_connector_reference,
    write_provider_live_credential_vault_reference,
    write_provider_live_network_policy_reference,
    write_provider_live_phase1_safety_boundary_reference,
    write_provider_live_runtime_ingest_boundary_reference,
    write_provider_live_executor_registration,
    write_provider_live_executor_fixture_replay,
    write_provider_live_executor_handoff_package,
    write_provider_live_executor_handoff_outbox_index,
    write_provider_live_executor_handoff_pickup_manifest,
    write_provider_live_executor_handoff_fixture_replay,
    write_provider_live_executor_pickup_response_manifest,
    write_provider_live_executor_readiness,
    write_provider_live_executor_response_inbox_index,
    write_provider_live_executor_response_manifest,
    write_provider_live_transport_materialization,
    write_provider_live_transport_response_admission_from_executor_response_manifest,
    write_provider_live_transport_response_admission,
    write_provider_live_transport_response_admission_from_fixture_replay,
    write_provider_live_transport_preflight,
    write_provider_live_transport_request_plan,
    write_provider_live_transport_sync_package,
)
from scout_energy_reserve import (
    write_provider_live_executor_pickup_response_consumption,
    write_provider_live_executor_pickup_response_consumption_receipt,
    write_provider_live_executor_pickup_status_snapshot,
    write_provider_live_executor_lifecycle_audit,
    write_provider_live_executor_production_readiness_gate,
    write_provider_live_executor_response_inbox_batch_receipt,
    write_provider_live_executor_response_inbox_batch_consumption,
    write_provider_live_executor_response_inbox_consumption,
    write_provider_live_executor_response_inbox_status_snapshot,
)
from scout_wearable_validator import validate_wearable_activity_summary_contract


ROOT = Path(__file__).resolve().parents[1]


def test_provider_live_transport_preflight_requires_explicit_consent_and_redacts_refs(tmp_path):
    try:
        write_provider_live_transport_preflight(
            provider="garmin_health_api_live",
            output_path=tmp_path / "preflight.json",
            explicit_consent=False,
            account_ref="garmin.account.private",
            auth_token_ref="secret-token-value",
            scopes=["activity:read"],
            requested_capabilities=["activity_summary_import"],
        )
    except ValueError as exc:
        assert "explicit consent" in str(exc)
    else:
        raise AssertionError("live transport preflight should require explicit consent")

    result = write_provider_live_transport_preflight(
        provider="garmin_health_api_live",
        output_path=tmp_path / "preflight.json",
        explicit_consent=True,
        account_ref="garmin.account.private",
        device_ref="garmin.watch.private",
        auth_token_ref="secret-token-value",
        scopes=["activity:read", "heart_rate:read"],
        requested_capabilities=["activity_summary_import", "heart_rate_samples"],
    )
    serialized = json.dumps(result)

    assert result["artifact_kind"] == "scout_wearable_provider_live_transport_preflight_result"
    assert result["source_provider"] == "garmin_health_api_live"
    assert Path(result["preflight_path"]).exists()
    assert result["preflight"]["artifact_kind"] == "scout_wearable_provider_live_transport_preflight"
    assert result["preflight"]["authorization"]["explicit_consent"] is True
    assert result["preflight"]["authorization"]["account_authorized"] is True
    assert result["preflight"]["authorization"]["token_value_exposed"] is False
    assert result["preflight"]["authorization"]["token_ref_sha256"] is not None
    assert result["preflight"]["authorization"]["account_ref_sha256"] is not None
    assert result["preflight"]["authorization"]["device_ref_sha256"] is not None
    assert result["preflight"]["transport"]["network_request_performed"] is False
    assert result["preflight"]["transport"]["real_provider_api_called"] is False
    assert result["preflight"]["transport"]["runtime_ingest_performed"] is False
    assert result["preflight"]["mutation"]["raw_payload_committed"] is False
    assert result["preflight"]["privacy"]["raw_health_payload_shared"] is False
    assert result["preflight"]["boundary"]["medical_diagnosis"] is False
    assert result["preflight"]["boundary"]["phase1_runtime_safety_truth"] is False
    assert "secret-token-value" not in serialized
    assert "garmin.account.private" not in serialized
    assert "garmin.watch.private" not in serialized


def test_provider_live_credential_vault_reference_requires_consent_and_redacts_refs(tmp_path):
    try:
        write_provider_live_credential_vault_reference(
            provider="garmin_health_api_live",
            output_path=tmp_path / "credential-vault-reference.json",
            explicit_consent=False,
            vault_ref="garmin.vault.private",
            account_ref="garmin.account.private",
            token_ref="secret-token-value",
            scopes=["activity:read"],
            capabilities=["activity_summary_import"],
        )
    except ValueError as exc:
        assert "explicit consent" in str(exc)
    else:
        raise AssertionError("credential vault reference should require explicit consent")

    result = write_provider_live_credential_vault_reference(
        provider="garmin_health_api_live",
        output_path=tmp_path / "credential-vault-reference.json",
        explicit_consent=True,
        vault_ref="garmin.vault.private",
        account_ref="garmin.account.private",
        device_ref="garmin.watch.private",
        token_ref="secret-token-value",
        scopes=["activity:read", "heart_rate:read", "body_energy:read"],
        capabilities=[
            "activity_summary_import",
            "heart_rate_samples",
            "provider_body_energy_source_values",
        ],
    )
    artifact = result["credential_vault_reference"]
    serialized = json.dumps(result)

    assert (
        result["artifact_kind"]
        == "scout_wearable_provider_live_credential_vault_reference_result"
    )
    assert Path(result["credential_vault_reference_path"]).exists()
    assert artifact["artifact_kind"] == "scout_wearable_provider_live_credential_vault_reference"
    assert artifact["source_provider"] == "garmin_health_api_live"
    assert artifact["credential_vault"]["vault_ref_sha256"] is not None
    assert artifact["credential_vault"]["account_ref_sha256"] is not None
    assert artifact["credential_vault"]["token_ref_sha256"] is not None
    assert artifact["credential_vault"]["device_ref_sha256"] is not None
    assert artifact["credential_vault"]["credential_values_loaded"] is False
    assert artifact["credential_vault"]["credential_values_exposed"] is False
    assert artifact["credential_vault"]["vault_lookup_performed"] is False
    assert artifact["credential_vault"]["vault_write_performed"] is False
    assert artifact["authorization"]["explicit_consent"] is True
    assert artifact["transport"]["transport_mode"] == "credential_vault_reference_only"
    assert artifact["transport"]["network_request_performed"] is False
    assert artifact["transport"]["real_provider_api_called"] is False
    assert artifact["transport"]["runtime_ingest_performed"] is False
    assert artifact["privacy"]["raw_health_payload_shared"] is False
    assert artifact["boundary"]["medical_diagnosis"] is False
    assert artifact["boundary"]["phase1_runtime_safety_truth"] is False
    assert "garmin.vault.private" not in serialized
    assert "secret-token-value" not in serialized
    assert "garmin.account.private" not in serialized
    assert "garmin.watch.private" not in serialized


def test_provider_live_connector_reference_requires_consent_and_redacts_refs(tmp_path):
    try:
        write_provider_live_connector_reference(
            provider="garmin_health_api_live",
            output_path=tmp_path / "connector-reference.json",
            explicit_consent=False,
            connector_kind="garmin_health_api_connector",
            connector_ref="garmin.connector.private",
            connector_version="garmin-connector-0.1.0",
            connector_binary_ref="garmin.connector.binary.private",
            supported_capabilities=["activity_summary_import"],
        )
    except ValueError as exc:
        assert "explicit consent" in str(exc)
    else:
        raise AssertionError("connector reference should require explicit consent")

    result = write_provider_live_connector_reference(
        provider="garmin_health_api_live",
        output_path=tmp_path / "connector-reference.json",
        explicit_consent=True,
        connector_kind="garmin_health_api_connector",
        connector_ref="garmin.connector.private",
        connector_version="garmin-connector-0.1.0",
        connector_binary_ref="garmin.connector.binary.private",
        supported_capabilities=[
            "activity_summary_import",
            "heart_rate_samples",
            "provider_body_energy_source_values",
        ],
    )
    artifact = result["connector_reference"]
    serialized = json.dumps(result)

    assert result["artifact_kind"] == "scout_wearable_provider_live_connector_reference_result"
    assert Path(result["connector_reference_path"]).exists()
    assert artifact["artifact_kind"] == "scout_wearable_provider_live_connector_reference"
    assert artifact["source_provider"] == "garmin_health_api_live"
    assert artifact["connector"]["connector_kind"] == "garmin_health_api_connector"
    assert artifact["connector"]["connector_ref_sha256"] is not None
    assert artifact["connector"]["connector_binary_ref_sha256"] is not None
    assert artifact["connector"]["connector_process_started"] is False
    assert artifact["connector"]["connector_health_check_performed"] is False
    assert artifact["connector"]["connector_live_request_performed"] is False
    assert artifact["connector"]["connector_execution_bound"] is False
    assert artifact["connector"]["credential_values_loaded"] is False
    assert artifact["connector"]["credential_values_exposed"] is False
    assert artifact["authorization"]["explicit_consent"] is True
    assert artifact["transport"]["transport_mode"] == "connector_reference_only"
    assert artifact["transport"]["network_request_performed"] is False
    assert artifact["transport"]["real_provider_api_called"] is False
    assert artifact["transport"]["runtime_ingest_performed"] is False
    assert artifact["privacy"]["raw_health_payload_shared"] is False
    assert artifact["boundary"]["medical_diagnosis"] is False
    assert artifact["boundary"]["phase1_runtime_safety_truth"] is False
    assert "garmin.connector.private" not in serialized
    assert "garmin.connector.binary.private" not in serialized


def test_provider_live_network_policy_reference_requires_consent_and_redacts_refs(tmp_path):
    try:
        write_provider_live_network_policy_reference(
            provider="garmin_health_api_live",
            output_path=tmp_path / "network-policy-reference.json",
            explicit_consent=False,
            policy_ref="garmin.network.policy.private",
            endpoint_ref="garmin.endpoint.private",
            egress_profile_ref="garmin.egress.private",
            tls_profile_ref="garmin.tls.private",
            allowed_capabilities=["activity_summary_import"],
        )
    except ValueError as exc:
        assert "explicit consent" in str(exc)
    else:
        raise AssertionError("network policy reference should require explicit consent")

    result = write_provider_live_network_policy_reference(
        provider="garmin_health_api_live",
        output_path=tmp_path / "network-policy-reference.json",
        explicit_consent=True,
        policy_ref="garmin.network.policy.private",
        endpoint_ref="garmin.endpoint.private",
        egress_profile_ref="garmin.egress.private",
        tls_profile_ref="garmin.tls.private",
        allowed_capabilities=[
            "activity_summary_import",
            "heart_rate_samples",
            "provider_body_energy_source_values",
        ],
    )
    artifact = result["network_policy_reference"]
    serialized = json.dumps(result)

    assert result["artifact_kind"] == "scout_wearable_provider_live_network_policy_reference_result"
    assert Path(result["network_policy_reference_path"]).exists()
    assert artifact["artifact_kind"] == "scout_wearable_provider_live_network_policy_reference"
    assert artifact["source_provider"] == "garmin_health_api_live"
    assert artifact["network_policy"]["policy_ref_sha256"] is not None
    assert artifact["network_policy"]["endpoint_ref_sha256"] is not None
    assert artifact["network_policy"]["egress_profile_ref_sha256"] is not None
    assert artifact["network_policy"]["tls_profile_ref_sha256"] is not None
    assert artifact["network_policy"]["dns_lookup_performed"] is False
    assert artifact["network_policy"]["network_socket_opened"] is False
    assert artifact["network_policy"]["tls_handshake_performed"] is False
    assert artifact["network_policy"]["http_request_performed"] is False
    assert artifact["network_policy"]["network_request_performed"] is False
    assert artifact["network_policy"]["real_provider_api_called"] is False
    assert artifact["network_policy"]["runtime_ingest_performed"] is False
    assert artifact["transport"]["transport_mode"] == "network_policy_reference_only"
    assert artifact["transport"]["network_request_performed"] is False
    assert artifact["transport"]["real_provider_api_called"] is False
    assert artifact["transport"]["runtime_ingest_performed"] is False
    assert artifact["privacy"]["raw_health_payload_shared"] is False
    assert artifact["boundary"]["medical_diagnosis"] is False
    assert artifact["boundary"]["phase1_runtime_safety_truth"] is False
    assert "garmin.network.policy.private" not in serialized
    assert "garmin.endpoint.private" not in serialized
    assert "garmin.egress.private" not in serialized
    assert "garmin.tls.private" not in serialized


def test_provider_live_runtime_ingest_boundary_reference_keeps_runtime_blocked(tmp_path):
    try:
        write_provider_live_runtime_ingest_boundary_reference(
            provider="garmin_health_api_live",
            output_path=tmp_path / "runtime-ingest-boundary-reference.json",
            explicit_consent=False,
            runtime_boundary_ref="phase1.runtime.boundary.private",
            runtime_channel_ref="energy.advisory.channel.private",
            allowed_artifact_kinds=[
                "scout_wearable_provider_live_executor_production_readiness_gate",
            ],
        )
    except ValueError as exc:
        assert "explicit consent" in str(exc)
    else:
        raise AssertionError("runtime ingest boundary reference should require explicit consent")

    result = write_provider_live_runtime_ingest_boundary_reference(
        provider="garmin_health_api_live",
        output_path=tmp_path / "runtime-ingest-boundary-reference.json",
        explicit_consent=True,
        runtime_boundary_ref="phase1.runtime.boundary.private",
        runtime_channel_ref="energy.advisory.channel.private",
        allowed_artifact_kinds=[
            "scout_wearable_provider_live_executor_production_readiness_gate",
            "scout_energy_reserve_baseline",
        ],
        handoff_mode="advisory_energy_reference_only",
    )
    artifact = result["runtime_ingest_boundary_reference"]
    serialized = json.dumps(result)

    assert (
        result["artifact_kind"]
        == "scout_wearable_provider_live_runtime_ingest_boundary_reference_result"
    )
    assert Path(result["runtime_ingest_boundary_reference_path"]).exists()
    assert (
        artifact["artifact_kind"]
        == "scout_wearable_provider_live_runtime_ingest_boundary_reference"
    )
    assert artifact["source_provider"] == "garmin_health_api_live"
    assert artifact["runtime_ingest_boundary"]["runtime_boundary_ref_sha256"] is not None
    assert artifact["runtime_ingest_boundary"]["runtime_channel_ref_sha256"] is not None
    assert artifact["runtime_ingest_boundary"]["runtime_ingest_authorized"] is False
    assert artifact["runtime_ingest_boundary"]["runtime_ingest_performed"] is False
    assert artifact["runtime_ingest_boundary"]["runtime_write_performed"] is False
    assert artifact["runtime_ingest_boundary"]["phase1_runtime_mutated"] is False
    assert artifact["runtime_ingest_boundary"]["phase1_runtime_safety_truth"] is False
    assert artifact["runtime_ingest_boundary"]["safety_api_called"] is False
    assert artifact["transport"]["transport_mode"] == "runtime_ingest_boundary_reference_only"
    assert artifact["transport"]["runtime_ingest_performed"] is False
    assert artifact["transport"]["safety_api_called"] is False
    assert artifact["privacy"]["raw_health_payload_shared"] is False
    assert artifact["boundary"]["medical_diagnosis"] is False
    assert artifact["boundary"]["phase1_runtime_safety_truth"] is False
    assert "phase1.runtime.boundary.private" not in serialized
    assert "energy.advisory.channel.private" not in serialized


def test_provider_live_phase1_safety_boundary_reference_keeps_safety_truth_blocked(tmp_path):
    try:
        write_provider_live_phase1_safety_boundary_reference(
            provider="garmin_health_api_live",
            output_path=tmp_path / "phase1-safety-boundary-reference.json",
            explicit_consent=False,
            phase1_boundary_ref="phase1.safety.boundary.private",
            phase1_state_ref="phase1.l0-l4.state.private",
            advisory_channel_ref="energy.advisory.channel.private",
            allowed_artifact_kinds=[
                "scout_wearable_provider_live_executor_production_readiness_gate",
            ],
        )
    except ValueError as exc:
        assert "explicit consent" in str(exc)
    else:
        raise AssertionError("Phase 1 safety boundary reference should require explicit consent")

    result = write_provider_live_phase1_safety_boundary_reference(
        provider="garmin_health_api_live",
        output_path=tmp_path / "phase1-safety-boundary-reference.json",
        explicit_consent=True,
        phase1_boundary_ref="phase1.safety.boundary.private",
        phase1_state_ref="phase1.l0-l4.state.private",
        advisory_channel_ref="energy.advisory.channel.private",
        allowed_artifact_kinds=[
            "scout_wearable_provider_live_executor_production_readiness_gate",
            "scout_energy_reserve_baseline",
        ],
    )
    artifact = result["phase1_safety_boundary_reference"]
    serialized = json.dumps(result)

    assert (
        result["artifact_kind"]
        == "scout_wearable_provider_live_phase1_safety_boundary_reference_result"
    )
    assert Path(result["phase1_safety_boundary_reference_path"]).exists()
    assert (
        artifact["artifact_kind"]
        == "scout_wearable_provider_live_phase1_safety_boundary_reference"
    )
    assert artifact["source_provider"] == "garmin_health_api_live"
    assert artifact["phase1_safety_boundary"]["phase1_boundary_ref_sha256"] is not None
    assert artifact["phase1_safety_boundary"]["phase1_state_ref_sha256"] is not None
    assert artifact["phase1_safety_boundary"]["advisory_channel_ref_sha256"] is not None
    assert artifact["phase1_safety_boundary"]["advisory_only"] is True
    assert artifact["phase1_safety_boundary"]["not_safety_truth"] is True
    assert artifact["phase1_safety_boundary"]["phase1_runtime_safety_truth"] is False
    assert artifact["phase1_safety_boundary"]["phase1_runtime_mutated"] is False
    assert artifact["phase1_safety_boundary"]["phase1_l0_l4_state_mutated"] is False
    assert artifact["phase1_safety_boundary"]["phase1_safety_state_mutation_allowed"] is False
    assert artifact["phase1_safety_boundary"]["safety_api_called"] is False
    assert artifact["phase1_safety_boundary"]["medical_diagnosis"] is False
    assert artifact["phase1_safety_boundary"]["provider_values_are_scout_truth"] is False
    assert artifact["transport"]["transport_mode"] == "phase1_safety_boundary_reference_only"
    assert artifact["transport"]["runtime_ingest_performed"] is False
    assert artifact["transport"]["phase1_l0_l4_state_mutated"] is False
    assert artifact["transport"]["safety_api_called"] is False
    assert artifact["privacy"]["raw_health_payload_shared"] is False
    assert artifact["boundary"]["medical_diagnosis"] is False
    assert artifact["boundary"]["phase1_runtime_safety_truth"] is False
    assert "phase1.safety.boundary.private" not in serialized
    assert "phase1.l0-l4.state.private" not in serialized
    assert "energy.advisory.channel.private" not in serialized
    assert "/safety/" not in serialized


def test_provider_live_transport_request_plan_uses_preflight_without_network(tmp_path):
    preflight_result = write_provider_live_transport_preflight(
        provider="garmin_health_api_live",
        output_path=tmp_path / "preflight.json",
        explicit_consent=True,
        account_ref="garmin.account.private",
        device_ref="garmin.watch.private",
        auth_token_ref="secret-token-value",
        scopes=["activity:read", "heart_rate:read", "body_energy:read"],
        requested_capabilities=[
            "activity_summary_import",
            "heart_rate_samples",
            "provider_body_energy_source_values",
        ],
    )

    result = write_provider_live_transport_request_plan(
        preflight_path=Path(preflight_result["preflight_path"]),
        output_path=tmp_path / "request-plan.json",
        window_start_date="2026-05-20",
        window_end_date="2026-05-27",
        requested_capabilities=["activity_summary_import", "provider_body_energy_source_values"],
    )
    plan = result["request_plan"]
    serialized = json.dumps(result)

    assert result["artifact_kind"] == "scout_wearable_provider_live_transport_request_plan_result"
    assert Path(result["request_plan_path"]).exists()
    assert plan["artifact_kind"] == "scout_wearable_provider_live_transport_request_plan"
    assert plan["source_provider"] == "garmin_health_api_live"
    assert plan["query_window"] == {
        "start_date": "2026-05-20",
        "end_date": "2026-05-27",
        "precision": "date_only",
    }
    assert [slot["capability"] for slot in plan["request_slots"]] == [
        "activity_summary_import",
        "provider_body_energy_source_values",
    ]
    assert plan["request_slots"][0]["provider_request_kind"] == "garmin_health_activity_summary_query"
    assert plan["request_slots"][1]["provider_request_kind"] == "garmin_health_body_energy_summary_query"
    assert all(slot["request_body_exposed"] is False for slot in plan["request_slots"])
    assert all(len(slot["request_descriptor_sha256"]) == 64 for slot in plan["request_slots"])
    assert plan["transport"]["transport_mode"] == "request_plan_only"
    assert plan["transport"]["request_executor_bound"] is False
    assert plan["transport"]["network_request_performed"] is False
    assert plan["transport"]["real_provider_api_called"] is False
    assert plan["transport"]["runtime_ingest_performed"] is False
    assert plan["mutation"]["raw_payload_committed"] is False
    assert plan["privacy"]["raw_health_payload_shared"] is False
    assert plan["privacy"]["exact_timestamps_shared"] is False
    assert plan["boundary"]["medical_diagnosis"] is False
    assert plan["boundary"]["phase1_runtime_safety_truth"] is False
    assert "secret-token-value" not in serialized
    assert "garmin.account.private" not in serialized
    assert "garmin.watch.private" not in serialized
    assert "/safety/" not in serialized

    readiness = write_provider_live_executor_readiness(
        request_plan_path=Path(result["request_plan_path"]),
        output_path=tmp_path / "executor-readiness.json",
    )
    readiness_payload = json.dumps(readiness)

    assert readiness["artifact_kind"] == "scout_wearable_provider_live_executor_readiness_result"
    assert readiness["executor_readiness"]["artifact_kind"] == "scout_wearable_provider_live_executor_readiness"
    assert readiness["executor_readiness"]["source_provider"] == "garmin_health_api_live"
    assert readiness["executor_readiness"]["ready_for_live_execution"] is False
    assert readiness["executor_readiness"]["execution_blockers"] == [
        "live_provider_executor_not_registered",
        "network_execution_disabled_by_local_contract",
    ]
    assert readiness["executor_readiness"]["prerequisite_review"]["request_plan_valid"] is True
    assert readiness["executor_readiness"]["prerequisite_review"]["request_slot_count"] == 2
    assert readiness["executor_readiness"]["transport"]["network_request_performed"] is False
    assert readiness["executor_readiness"]["transport"]["real_provider_api_called"] is False
    assert readiness["executor_readiness"]["transport"]["runtime_ingest_performed"] is False
    assert readiness["executor_readiness"]["mutation"]["safety_api_called"] is False
    assert Path(readiness["executor_readiness_path"]).exists()
    assert "secret-token-value" not in readiness_payload
    assert "garmin.account.private" not in readiness_payload
    assert "garmin.watch.private" not in readiness_payload
    assert "/safety/" not in readiness_payload

    registration = write_provider_live_executor_registration(
        preflight_path=Path(preflight_result["preflight_path"]),
        output_path=tmp_path / "executor-registration.json",
        executor_kind="garmin_health_api_client",
        executor_ref="local.garmin.executor.private",
        supported_capabilities=["activity_summary_import", "provider_body_energy_source_values"],
    )
    registration_payload = json.dumps(registration)

    assert registration["artifact_kind"] == "scout_wearable_provider_live_executor_registration_result"
    assert registration["executor_registration"]["artifact_kind"] == "scout_wearable_provider_live_executor_registration"
    assert registration["executor_registration"]["source_provider"] == "garmin_health_api_live"
    assert registration["executor_registration"]["executor_registration"]["executor_registered"] is True
    assert registration["executor_registration"]["executor_registration"]["executor_ref_exposed"] is False
    assert registration["executor_registration"]["transport"]["network_request_performed"] is False
    assert registration["executor_registration"]["transport"]["real_provider_api_called"] is False
    assert registration["executor_registration"]["transport"]["runtime_ingest_performed"] is False
    assert "local.garmin.executor.private" not in registration_payload
    assert "secret-token-value" not in registration_payload
    assert "garmin.account.private" not in registration_payload
    assert "garmin.watch.private" not in registration_payload
    assert "/safety/" not in registration_payload

    readiness_with_registration = write_provider_live_executor_readiness(
        request_plan_path=Path(result["request_plan_path"]),
        executor_registration_path=Path(registration["executor_registration_path"]),
        output_path=tmp_path / "executor-readiness-registered.json",
    )

    assert readiness_with_registration["executor_readiness"]["ready_for_live_execution"] is False
    assert readiness_with_registration["executor_readiness"]["execution_blockers"] == [
        "network_execution_disabled_by_local_contract"
    ]
    assert (
        readiness_with_registration["executor_readiness"]["executor_registration"]["executor_registered"]
        is True
    )

    handoff = write_provider_live_executor_handoff_package(
        request_plan_path=Path(result["request_plan_path"]),
        executor_registration_path=Path(registration["executor_registration_path"]),
        output_path=tmp_path / "executor-handoff.json",
    )
    handoff_payload = json.dumps(handoff)

    assert handoff["artifact_kind"] == "scout_wearable_provider_live_executor_handoff_package_result"
    assert handoff["executor_handoff"]["artifact_kind"] == "scout_wearable_provider_live_executor_handoff_package"
    assert handoff["executor_handoff"]["source_provider"] == "garmin_health_api_live"
    assert handoff["executor_handoff"]["readiness"]["execution_blockers"] == [
        "network_execution_disabled_by_local_contract"
    ]
    assert handoff["executor_handoff"]["request_descriptor_count"] == 2
    assert handoff["executor_handoff"]["executor_registration"]["executor_ref_exposed"] is False
    assert handoff["executor_handoff"]["transport"]["transport_mode"] == "executor_handoff_package_only"
    assert handoff["executor_handoff"]["transport"]["request_executor_bound"] is False
    assert handoff["executor_handoff"]["transport"]["network_request_performed"] is False
    assert handoff["executor_handoff"]["transport"]["real_provider_api_called"] is False
    assert handoff["executor_handoff"]["transport"]["runtime_ingest_performed"] is False
    assert Path(handoff["executor_handoff_path"]).exists()
    assert "local.garmin.executor.private" not in handoff_payload
    assert "secret-token-value" not in handoff_payload
    assert "garmin.account.private" not in handoff_payload
    assert "garmin.watch.private" not in handoff_payload
    assert "/safety/" not in handoff_payload

    handoff_outbox_dir = tmp_path / "executor-handoff-outbox"
    handoff_outbox_dir.mkdir()
    handoff_outbox_path = handoff_outbox_dir / "garmin-executor-handoff.json"
    handoff_outbox_path.write_text(
        Path(handoff["executor_handoff_path"]).read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (handoff_outbox_dir / "not-a-handoff.json").write_text(
        json.dumps({"artifact_kind": "unrelated_local_artifact"}),
        encoding="utf-8",
    )
    handoff_outbox_index = write_provider_live_executor_handoff_outbox_index(
        outbox_dir=handoff_outbox_dir,
        output_path=tmp_path / "executor-handoff-outbox-index.json",
    )
    handoff_outbox_index_payload = json.dumps(handoff_outbox_index)

    assert (
        handoff_outbox_index["artifact_kind"]
        == "scout_wearable_provider_live_executor_handoff_outbox_index_result"
    )
    assert Path(handoff_outbox_index["executor_handoff_outbox_index_path"]).exists()
    assert handoff_outbox_index["executor_handoff_outbox_index"]["source_provider"] == "garmin_health_api_live"
    assert handoff_outbox_index["executor_handoff_outbox_index"]["outbox"]["json_file_count"] == 2
    assert handoff_outbox_index["executor_handoff_outbox_index"]["outbox"]["eligible_handoff_count"] == 1
    assert handoff_outbox_index["executor_handoff_outbox_index"]["outbox"]["rejected_file_count"] == 1
    eligible_handoff = [
        entry
        for entry in handoff_outbox_index["executor_handoff_outbox_index"]["handoff_packages"]
        if entry["eligible_for_executor_pickup_precheck"]
    ][0]
    assert eligible_handoff["request_plan_ref_valid"] is True
    assert eligible_handoff["executor_registration_ref_valid"] is True
    assert eligible_handoff["handoff_package_sha256"] == handoff["executor_handoff"]["sha256"]
    assert handoff_outbox_index["executor_handoff_outbox_index"]["transport"]["network_request_performed"] is False
    assert handoff_outbox_index["executor_handoff_outbox_index"]["transport"]["real_provider_api_called"] is False
    assert handoff_outbox_index["executor_handoff_outbox_index"]["transport"]["runtime_ingest_performed"] is False
    assert "local.garmin.executor.private" not in handoff_outbox_index_payload
    assert "secret-token-value" not in handoff_outbox_index_payload
    assert "garmin.account.private" not in handoff_outbox_index_payload
    assert "garmin.watch.private" not in handoff_outbox_index_payload
    assert "/safety/" not in handoff_outbox_index_payload

    handoff_pickup = write_provider_live_executor_handoff_pickup_manifest(
        outbox_index_path=Path(handoff_outbox_index["executor_handoff_outbox_index_path"]),
        output_path=tmp_path / "executor-handoff-pickup-manifest.json",
    )
    handoff_pickup_payload = json.dumps(handoff_pickup)

    assert (
        handoff_pickup["artifact_kind"]
        == "scout_wearable_provider_live_executor_handoff_pickup_manifest_result"
    )
    assert Path(handoff_pickup["executor_handoff_pickup_manifest_path"]).exists()
    assert handoff_pickup["executor_handoff_path"] == str(handoff_outbox_path)
    assert handoff_pickup["executor_handoff_pickup_manifest"]["pickup"]["pickup_status"] == (
        "ready_for_external_executor_review"
    )
    assert (
        handoff_pickup["executor_handoff_pickup_manifest"]["pickup"]["external_execution_authorized"]
        is False
    )
    assert (
        handoff_pickup["executor_handoff_pickup_manifest"]["pickup"][
            "network_execution_disabled_by_local_contract"
        ]
        is True
    )
    assert handoff_pickup["executor_handoff_pickup_manifest"]["transport"]["network_request_performed"] is False
    assert handoff_pickup["executor_handoff_pickup_manifest"]["transport"]["real_provider_api_called"] is False
    assert handoff_pickup["executor_handoff_pickup_manifest"]["transport"]["runtime_ingest_performed"] is False
    assert "local.garmin.executor.private" not in handoff_pickup_payload
    assert "secret-token-value" not in handoff_pickup_payload
    assert "garmin.account.private" not in handoff_pickup_payload
    assert "garmin.watch.private" not in handoff_pickup_payload
    assert "/safety/" not in handoff_pickup_payload

    response_fixture_path = _write_garmin_health_api_response_fixture(tmp_path / "garmin-response.json")
    pickup_response_manifest = write_provider_live_executor_pickup_response_manifest(
        pickup_manifest_path=Path(handoff_pickup["executor_handoff_pickup_manifest_path"]),
        response_payload_path=response_fixture_path,
        output_path=tmp_path / "executor-pickup-response-manifest.json",
    )
    pickup_response_manifest_payload = json.dumps(pickup_response_manifest)

    assert (
        pickup_response_manifest["artifact_kind"]
        == "scout_wearable_provider_live_executor_pickup_response_manifest_result"
    )
    assert Path(pickup_response_manifest["executor_response_manifest_path"]).exists()
    assert (
        pickup_response_manifest["executor_response_manifest"]["artifact_kind"]
        == "scout_wearable_provider_live_executor_response_manifest"
    )
    assert pickup_response_manifest["executor_response_manifest"]["source_provider"] == "garmin_health_api_live"
    assert (
        pickup_response_manifest["executor_response_manifest"]["pickup_manifest"]["sha256"]
        == handoff_pickup["executor_handoff_pickup_manifest"]["sha256"]
    )
    assert (
        pickup_response_manifest["executor_response_manifest"]["pickup_manifest"][
            "external_execution_authorized"
        ]
        is False
    )
    assert (
        pickup_response_manifest["executor_response_manifest"]["handoff_package"]["sha256"]
        == handoff["executor_handoff"]["sha256"]
    )
    assert (
        pickup_response_manifest["executor_response_manifest"]["response_payload"]["raw_response_embedded"]
        is False
    )
    assert pickup_response_manifest["executor_response_manifest"]["transport"]["network_request_performed"] is False
    assert pickup_response_manifest["executor_response_manifest"]["transport"]["real_provider_api_called"] is False
    assert pickup_response_manifest["executor_response_manifest"]["transport"]["runtime_ingest_performed"] is False
    assert "heartRateSamples" not in pickup_response_manifest_payload
    assert "geoPolylineDTO" not in pickup_response_manifest_payload
    assert "local.garmin.executor.private" not in pickup_response_manifest_payload
    assert "secret-token-value" not in pickup_response_manifest_payload
    assert "garmin.account.private" not in pickup_response_manifest_payload
    assert "garmin.watch.private" not in pickup_response_manifest_payload
    assert "/safety/" not in pickup_response_manifest_payload

    pickup_response_consumption = write_provider_live_executor_pickup_response_consumption(
        executor_response_manifest_path=Path(
            pickup_response_manifest["executor_response_manifest_path"]
        ),
        output_dir=tmp_path / "pickup-response-consumption",
        activity_id_prefix="live.garmin.pickup.response.consumed",
        admitted_capabilities=["activity_summary_import", "provider_body_energy_source_values"],
        reference_date=None,
        root=tmp_path,
    )
    pickup_response_consumption_payload = json.dumps(pickup_response_consumption)

    assert (
        pickup_response_consumption["artifact_kind"]
        == "scout_wearable_provider_live_executor_pickup_response_consumption_result"
    )
    assert Path(pickup_response_consumption["executor_pickup_response_consumption_path"]).exists()
    assert Path(pickup_response_consumption["baseline_path"]).exists()
    assert (
        pickup_response_consumption["executor_pickup_response_consumption"]["pickup_manifest"]["sha256"]
        == handoff_pickup["executor_handoff_pickup_manifest"]["sha256"]
    )
    assert (
        pickup_response_consumption["executor_response_consumption"]["executor_response_manifest"][
            "pickup_manifest_sha256"
        ]
        == handoff_pickup["executor_handoff_pickup_manifest"]["sha256"]
    )
    assert (
        pickup_response_consumption["executor_pickup_response_consumption"]["transport"][
            "network_request_performed"
        ]
        is False
    )
    assert (
        pickup_response_consumption["executor_pickup_response_consumption"]["transport"][
            "real_provider_api_called"
        ]
        is False
    )
    assert (
        pickup_response_consumption["executor_pickup_response_consumption"]["transport"][
            "runtime_ingest_performed"
        ]
        is False
    )
    assert "heartRateSamples" not in pickup_response_consumption_payload
    assert "geoPolylineDTO" not in pickup_response_consumption_payload
    assert "local.garmin.executor.private" not in pickup_response_consumption_payload
    assert "secret-token-value" not in pickup_response_consumption_payload
    assert "garmin.account.private" not in pickup_response_consumption_payload
    assert "garmin.watch.private" not in pickup_response_consumption_payload
    assert "/safety/" not in pickup_response_consumption_payload

    pickup_response_receipt = write_provider_live_executor_pickup_response_consumption_receipt(
        pickup_response_consumption_path=Path(
            pickup_response_consumption["executor_pickup_response_consumption_path"]
        ),
        output_path=tmp_path / "pickup-response-consumption-receipt.json",
    )
    pickup_response_receipt_payload = json.dumps(pickup_response_receipt)

    assert (
        pickup_response_receipt["artifact_kind"]
        == "scout_wearable_provider_live_executor_pickup_response_consumption_receipt_result"
    )
    assert Path(
        pickup_response_receipt["executor_pickup_response_consumption_receipt_path"]
    ).exists()
    assert (
        pickup_response_receipt["executor_pickup_response_consumption_receipt"][
            "pickup_response_consumption"
        ]["sha256"]
        == pickup_response_consumption["executor_pickup_response_consumption"]["sha256"]
    )
    assert (
        pickup_response_receipt["executor_pickup_response_consumption_receipt"][
            "pickup_manifest"
        ]["sha256"]
        == handoff_pickup["executor_handoff_pickup_manifest"]["sha256"]
    )
    assert (
        pickup_response_receipt["executor_pickup_response_consumption_receipt"][
            "receipt"
        ]["receipt_status"]
        == "locally_recorded"
    )
    assert (
        pickup_response_receipt["executor_pickup_response_consumption_receipt"][
            "transport"
        ]["network_request_performed"]
        is False
    )
    assert (
        pickup_response_receipt["executor_pickup_response_consumption_receipt"][
            "transport"
        ]["real_provider_api_called"]
        is False
    )
    assert (
        pickup_response_receipt["executor_pickup_response_consumption_receipt"][
            "transport"
        ]["runtime_ingest_performed"]
        is False
    )
    assert "heartRateSamples" not in pickup_response_receipt_payload
    assert "geoPolylineDTO" not in pickup_response_receipt_payload
    assert "local.garmin.executor.private" not in pickup_response_receipt_payload
    assert "secret-token-value" not in pickup_response_receipt_payload
    assert "garmin.account.private" not in pickup_response_receipt_payload
    assert "garmin.watch.private" not in pickup_response_receipt_payload
    assert "/safety/" not in pickup_response_receipt_payload

    pickup_status_snapshot = write_provider_live_executor_pickup_status_snapshot(
        pickup_manifest_path=Path(
            handoff_pickup["executor_handoff_pickup_manifest_path"]
        ),
        executor_response_manifest_path=Path(
            pickup_response_manifest["executor_response_manifest_path"]
        ),
        pickup_response_consumption_path=Path(
            pickup_response_consumption["executor_pickup_response_consumption_path"]
        ),
        pickup_response_receipt_path=Path(
            pickup_response_receipt[
                "executor_pickup_response_consumption_receipt_path"
            ]
        ),
        output_path=tmp_path / "pickup-status-snapshot.json",
    )
    pickup_status_snapshot_payload = json.dumps(pickup_status_snapshot)

    assert (
        pickup_status_snapshot["artifact_kind"]
        == "scout_wearable_provider_live_executor_pickup_status_snapshot_result"
    )
    assert Path(pickup_status_snapshot["executor_pickup_status_snapshot_path"]).exists()
    assert pickup_status_snapshot["pickup_lifecycle_status"] == "receipt_recorded"
    assert (
        pickup_status_snapshot["executor_pickup_status_snapshot"]["pickup_manifest"][
            "sha256"
        ]
        == handoff_pickup["executor_handoff_pickup_manifest"]["sha256"]
    )
    assert (
        pickup_status_snapshot["executor_pickup_status_snapshot"]["status"][
            "local_evidence_complete"
        ]
        is True
    )
    assert (
        pickup_status_snapshot["executor_pickup_status_snapshot"]["transport"][
            "network_request_performed"
        ]
        is False
    )
    assert (
        pickup_status_snapshot["executor_pickup_status_snapshot"]["transport"][
            "real_provider_api_called"
        ]
        is False
    )
    assert (
        pickup_status_snapshot["executor_pickup_status_snapshot"]["transport"][
            "runtime_ingest_performed"
        ]
        is False
    )
    assert "heartRateSamples" not in pickup_status_snapshot_payload
    assert "geoPolylineDTO" not in pickup_status_snapshot_payload
    assert "local.garmin.executor.private" not in pickup_status_snapshot_payload
    assert "secret-token-value" not in pickup_status_snapshot_payload
    assert "garmin.account.private" not in pickup_status_snapshot_payload
    assert "garmin.watch.private" not in pickup_status_snapshot_payload
    assert "/safety/" not in pickup_status_snapshot_payload

    handoff_replay = write_provider_live_executor_handoff_fixture_replay(
        handoff_package_path=Path(handoff["executor_handoff_path"]),
        response_fixture_path=response_fixture_path,
        output_path=tmp_path / "executor-handoff-fixture-replay.json",
    )
    handoff_replay_payload = json.dumps(handoff_replay)

    assert handoff_replay["artifact_kind"] == "scout_wearable_provider_live_executor_handoff_fixture_replay_result"
    assert (
        handoff_replay["executor_fixture_replay"]["artifact_kind"]
        == "scout_wearable_provider_live_executor_fixture_replay"
    )
    assert handoff_replay["executor_fixture_replay"]["source_provider"] == "garmin_health_api_live"
    assert (
        handoff_replay["executor_fixture_replay"]["handoff_package"]["sha256"]
        == handoff["executor_handoff"]["sha256"]
    )
    assert handoff_replay["executor_fixture_replay"]["transport"]["transport_mode"] == "executor_fixture_replay_only"
    assert handoff_replay["executor_fixture_replay"]["transport"]["network_request_performed"] is False
    assert handoff_replay["executor_fixture_replay"]["transport"]["real_provider_api_called"] is False
    assert handoff_replay["executor_fixture_replay"]["transport"]["runtime_ingest_performed"] is False
    assert Path(handoff_replay["executor_fixture_replay_path"]).exists()
    assert "heartRateSamples" not in handoff_replay_payload
    assert "geoPolylineDTO" not in handoff_replay_payload
    assert "local.garmin.executor.private" not in handoff_replay_payload
    assert "secret-token-value" not in handoff_replay_payload
    assert "garmin.account.private" not in handoff_replay_payload
    assert "garmin.watch.private" not in handoff_replay_payload
    assert "/safety/" not in handoff_replay_payload

    response_manifest = write_provider_live_executor_response_manifest(
        handoff_package_path=Path(handoff["executor_handoff_path"]),
        response_payload_path=response_fixture_path,
        output_path=tmp_path / "executor-response-manifest.json",
    )
    response_manifest_payload = json.dumps(response_manifest)

    assert response_manifest["artifact_kind"] == "scout_wearable_provider_live_executor_response_manifest_result"
    assert (
        response_manifest["executor_response_manifest"]["artifact_kind"]
        == "scout_wearable_provider_live_executor_response_manifest"
    )
    assert response_manifest["executor_response_manifest"]["source_provider"] == "garmin_health_api_live"
    assert (
        response_manifest["executor_response_manifest"]["handoff_package"]["sha256"]
        == handoff["executor_handoff"]["sha256"]
    )
    assert response_manifest["executor_response_manifest"]["response_payload"]["raw_response_embedded"] is False
    assert response_manifest["executor_response_manifest"]["transport"]["transport_mode"] == "executor_response_manifest_only"
    assert response_manifest["executor_response_manifest"]["transport"]["network_request_performed"] is False
    assert response_manifest["executor_response_manifest"]["transport"]["real_provider_api_called"] is False
    assert response_manifest["executor_response_manifest"]["transport"]["runtime_ingest_performed"] is False
    assert Path(response_manifest["executor_response_manifest_path"]).exists()
    assert "heartRateSamples" not in response_manifest_payload
    assert "geoPolylineDTO" not in response_manifest_payload
    assert "local.garmin.executor.private" not in response_manifest_payload
    assert "secret-token-value" not in response_manifest_payload
    assert "garmin.account.private" not in response_manifest_payload
    assert "garmin.watch.private" not in response_manifest_payload
    assert "/safety/" not in response_manifest_payload

    inbox_dir = tmp_path / "executor-response-inbox"
    inbox_dir.mkdir()
    inbox_manifest_path = inbox_dir / "garmin-response-manifest.json"
    inbox_manifest_path.write_text(
        Path(response_manifest["executor_response_manifest_path"]).read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (inbox_dir / "not-a-manifest.json").write_text(
        json.dumps({"artifact_kind": "unrelated_local_artifact"}),
        encoding="utf-8",
    )
    inbox_index = write_provider_live_executor_response_inbox_index(
        inbox_dir=inbox_dir,
        output_path=tmp_path / "executor-response-inbox-index.json",
    )
    inbox_index_payload = json.dumps(inbox_index)

    assert inbox_index["artifact_kind"] == "scout_wearable_provider_live_executor_response_inbox_index_result"
    assert Path(inbox_index["executor_response_inbox_index_path"]).exists()
    assert inbox_index["executor_response_inbox_index"]["source_provider"] == "garmin_health_api_live"
    assert inbox_index["executor_response_inbox_index"]["inbox"]["json_file_count"] == 2
    assert inbox_index["executor_response_inbox_index"]["inbox"]["eligible_manifest_count"] == 1
    assert inbox_index["executor_response_inbox_index"]["inbox"]["rejected_manifest_count"] == 1
    eligible_manifest = [
        entry
        for entry in inbox_index["executor_response_inbox_index"]["manifests"]
        if entry["eligible_for_consumption_precheck"]
    ][0]
    assert eligible_manifest["handoff_ref_valid"] is True
    assert eligible_manifest["response_payload_ref_valid"] is True
    assert eligible_manifest["handoff_package_sha256"] == handoff["executor_handoff"]["sha256"]
    assert inbox_index["executor_response_inbox_index"]["transport"]["network_request_performed"] is False
    assert inbox_index["executor_response_inbox_index"]["transport"]["real_provider_api_called"] is False
    assert inbox_index["executor_response_inbox_index"]["transport"]["runtime_ingest_performed"] is False
    assert "heartRateSamples" not in inbox_index_payload
    assert "geoPolylineDTO" not in inbox_index_payload
    assert "local.garmin.executor.private" not in inbox_index_payload
    assert "secret-token-value" not in inbox_index_payload
    assert "garmin.account.private" not in inbox_index_payload
    assert "garmin.watch.private" not in inbox_index_payload
    assert "/safety/" not in inbox_index_payload

    inbox_consumption = write_provider_live_executor_response_inbox_consumption(
        inbox_index_path=Path(inbox_index["executor_response_inbox_index_path"]),
        output_dir=tmp_path / "inbox-consumption",
        activity_id_prefix="live.garmin.inbox.consumed",
        admitted_capabilities=["activity_summary_import", "provider_body_energy_source_values"],
        reference_date=None,
        root=tmp_path,
    )
    inbox_consumption_payload = json.dumps(inbox_consumption)

    assert (
        inbox_consumption["artifact_kind"]
        == "scout_wearable_provider_live_executor_response_inbox_consumption_result"
    )
    assert Path(inbox_consumption["executor_response_inbox_consumption_path"]).exists()
    assert Path(inbox_consumption["baseline_path"]).exists()
    assert inbox_consumption["executor_response_manifest_path"] == str(inbox_manifest_path)
    assert (
        inbox_consumption["executor_response_inbox_consumption"]["selected_manifest"]["file_sha256"]
        == eligible_manifest["file_sha256"]
    )
    assert inbox_consumption["executor_response_inbox_consumption"]["transport"]["network_request_performed"] is False
    assert inbox_consumption["executor_response_inbox_consumption"]["transport"]["real_provider_api_called"] is False
    assert inbox_consumption["executor_response_inbox_consumption"]["transport"]["runtime_ingest_performed"] is False
    assert inbox_consumption["executor_response_consumption"]["energy_artifacts"]["baseline"]["activity_count"] == 2
    assert "heartRateSamples" not in inbox_consumption_payload
    assert "geoPolylineDTO" not in inbox_consumption_payload
    assert "local.garmin.executor.private" not in inbox_consumption_payload
    assert "secret-token-value" not in inbox_consumption_payload
    assert "garmin.account.private" not in inbox_consumption_payload
    assert "garmin.watch.private" not in inbox_consumption_payload
    assert "/safety/" not in inbox_consumption_payload

    batch_consumption = write_provider_live_executor_response_inbox_batch_consumption(
        inbox_index_path=Path(inbox_index["executor_response_inbox_index_path"]),
        output_dir=tmp_path / "inbox-batch-consumption",
        activity_id_prefix="live.garmin.inbox.batch.consumed",
        admitted_capabilities=["activity_summary_import", "provider_body_energy_source_values"],
        reference_date=None,
        root=tmp_path,
    )
    batch_consumption_payload = json.dumps(batch_consumption)

    assert (
        batch_consumption["artifact_kind"]
        == "scout_wearable_provider_live_executor_response_inbox_batch_consumption_result"
    )
    assert Path(batch_consumption["executor_response_inbox_batch_consumption_path"]).exists()
    assert batch_consumption["consumed_manifest_count"] == 1
    assert len(batch_consumption["executor_response_consumption_paths"]) == 1
    assert all(Path(path).exists() for path in batch_consumption["baseline_paths"])
    assert (
        batch_consumption["executor_response_inbox_batch_consumption"]["batch"]["selection_policy"]
        == "all_eligible_sorted_by_source_path"
    )
    assert batch_consumption["executor_response_inbox_batch_consumption"]["transport"]["network_request_performed"] is False
    assert batch_consumption["executor_response_inbox_batch_consumption"]["transport"]["real_provider_api_called"] is False
    assert batch_consumption["executor_response_inbox_batch_consumption"]["transport"]["runtime_ingest_performed"] is False
    assert "heartRateSamples" not in batch_consumption_payload
    assert "geoPolylineDTO" not in batch_consumption_payload
    assert "local.garmin.executor.private" not in batch_consumption_payload
    assert "secret-token-value" not in batch_consumption_payload
    assert "garmin.account.private" not in batch_consumption_payload
    assert "garmin.watch.private" not in batch_consumption_payload
    assert "/safety/" not in batch_consumption_payload

    batch_receipt = write_provider_live_executor_response_inbox_batch_receipt(
        batch_consumption_path=Path(batch_consumption["executor_response_inbox_batch_consumption_path"]),
        output_path=tmp_path / "inbox-batch-receipt.json",
    )
    batch_receipt_payload = json.dumps(batch_receipt)

    assert (
        batch_receipt["artifact_kind"]
        == "scout_wearable_provider_live_executor_response_inbox_batch_receipt_result"
    )
    assert Path(batch_receipt["executor_response_inbox_batch_receipt_path"]).exists()
    assert batch_receipt["consumed_manifest_count"] == 1
    assert batch_receipt["executor_response_inbox_batch_receipt"]["transport"]["network_request_performed"] is False
    assert batch_receipt["executor_response_inbox_batch_receipt"]["transport"]["real_provider_api_called"] is False
    assert batch_receipt["executor_response_inbox_batch_receipt"]["transport"]["runtime_ingest_performed"] is False
    assert (
        batch_receipt["executor_response_inbox_batch_receipt"]["receipts"][0]["receipt_status"]
        == "locally_recorded"
    )
    assert batch_receipt["executor_response_inbox_batch_receipt"]["receipts"][0]["baseline_path"] in (
        batch_consumption["baseline_paths"]
    )
    assert "heartRateSamples" not in batch_receipt_payload
    assert "geoPolylineDTO" not in batch_receipt_payload
    assert "local.garmin.executor.private" not in batch_receipt_payload
    assert "secret-token-value" not in batch_receipt_payload
    assert "garmin.account.private" not in batch_receipt_payload
    assert "garmin.watch.private" not in batch_receipt_payload
    assert "/safety/" not in batch_receipt_payload

    status_snapshot = write_provider_live_executor_response_inbox_status_snapshot(
        inbox_index_path=Path(inbox_index["executor_response_inbox_index_path"]),
        batch_consumption_path=Path(batch_consumption["executor_response_inbox_batch_consumption_path"]),
        batch_receipt_path=Path(batch_receipt["executor_response_inbox_batch_receipt_path"]),
        output_path=tmp_path / "inbox-status-snapshot.json",
    )
    status_snapshot_payload = json.dumps(status_snapshot)

    assert (
        status_snapshot["artifact_kind"]
        == "scout_wearable_provider_live_executor_response_inbox_status_snapshot_result"
    )
    assert Path(status_snapshot["executor_response_inbox_status_snapshot_path"]).exists()
    assert status_snapshot["manifest_status_counts"]["receipt_recorded_manifest_count"] == 1
    assert status_snapshot["manifest_status_counts"]["eligible_pending_manifest_count"] == 0
    assert (
        status_snapshot["executor_response_inbox_status_snapshot"]["manifest_statuses"][0][
            "manifest_status"
        ]
        == "receipt_recorded"
    )
    assert status_snapshot["executor_response_inbox_status_snapshot"]["transport"]["network_request_performed"] is False
    assert status_snapshot["executor_response_inbox_status_snapshot"]["transport"]["real_provider_api_called"] is False
    assert status_snapshot["executor_response_inbox_status_snapshot"]["transport"]["runtime_ingest_performed"] is False
    assert "heartRateSamples" not in status_snapshot_payload
    assert "geoPolylineDTO" not in status_snapshot_payload
    assert "local.garmin.executor.private" not in status_snapshot_payload
    assert "secret-token-value" not in status_snapshot_payload
    assert "garmin.account.private" not in status_snapshot_payload
    assert "garmin.watch.private" not in status_snapshot_payload
    assert "/safety/" not in status_snapshot_payload

    lifecycle_audit = write_provider_live_executor_lifecycle_audit(
        pickup_status_snapshot_path=Path(
            pickup_status_snapshot["executor_pickup_status_snapshot_path"]
        ),
        inbox_status_snapshot_path=Path(
            status_snapshot["executor_response_inbox_status_snapshot_path"]
        ),
        output_path=tmp_path / "executor-lifecycle-audit.json",
    )
    lifecycle_audit_payload = json.dumps(lifecycle_audit)

    assert (
        lifecycle_audit["artifact_kind"]
        == "scout_wearable_provider_live_executor_lifecycle_audit_result"
    )
    assert Path(lifecycle_audit["executor_lifecycle_audit_path"]).exists()
    assert lifecycle_audit["local_executor_lifecycle_status"] == "local_evidence_complete"
    assert lifecycle_audit["executor_lifecycle_audit"]["lifecycle"][
        "pickup_local_evidence_complete"
    ] is True
    assert lifecycle_audit["executor_lifecycle_audit"]["lifecycle"][
        "inbox_local_evidence_complete"
    ] is True
    assert lifecycle_audit["executor_lifecycle_audit"]["transport"][
        "network_request_performed"
    ] is False
    assert lifecycle_audit["executor_lifecycle_audit"]["transport"][
        "real_provider_api_called"
    ] is False
    assert lifecycle_audit["executor_lifecycle_audit"]["transport"][
        "runtime_ingest_performed"
    ] is False
    assert "heartRateSamples" not in lifecycle_audit_payload
    assert "geoPolylineDTO" not in lifecycle_audit_payload
    assert "local.garmin.executor.private" not in lifecycle_audit_payload
    assert "secret-token-value" not in lifecycle_audit_payload
    assert "garmin.account.private" not in lifecycle_audit_payload
    assert "garmin.watch.private" not in lifecycle_audit_payload
    assert "/safety/" not in lifecycle_audit_payload

    production_gate = write_provider_live_executor_production_readiness_gate(
        lifecycle_audit_path=Path(lifecycle_audit["executor_lifecycle_audit_path"]),
        output_path=tmp_path / "executor-production-readiness-gate.json",
    )
    production_gate_payload = json.dumps(production_gate)

    assert (
        production_gate["artifact_kind"]
        == "scout_wearable_provider_live_executor_production_readiness_gate_result"
    )
    assert Path(production_gate["executor_production_readiness_gate_path"]).exists()
    assert production_gate["production_provider_execution_ready"] is False
    assert (
        "live_provider_connector_not_implemented"
        in production_gate["production_blockers"]
    )
    assert (
        "credential_vault_not_integrated"
        in production_gate["production_blockers"]
    )
    assert production_gate["executor_production_readiness_gate"]["readiness"][
        "local_evidence_complete"
    ] is True
    assert production_gate["executor_production_readiness_gate"]["transport"][
        "network_request_performed"
    ] is False
    assert production_gate["executor_production_readiness_gate"]["transport"][
        "real_provider_api_called"
    ] is False
    assert production_gate["executor_production_readiness_gate"]["transport"][
        "runtime_ingest_performed"
    ] is False
    assert "heartRateSamples" not in production_gate_payload
    assert "geoPolylineDTO" not in production_gate_payload
    assert "local.garmin.executor.private" not in production_gate_payload
    assert "secret-token-value" not in production_gate_payload
    assert "garmin.account.private" not in production_gate_payload
    assert "garmin.watch.private" not in production_gate_payload
    assert "/safety/" not in production_gate_payload

    credential_vault_reference = write_provider_live_credential_vault_reference(
        provider="garmin_health_api_live",
        output_path=tmp_path / "credential-vault-reference.json",
        explicit_consent=True,
        vault_ref="garmin.vault.private",
        account_ref="garmin.account.private",
        device_ref="garmin.watch.private",
        token_ref="secret-token-value",
        scopes=["activity:read", "heart_rate:read", "body_energy:read"],
        capabilities=[
            "activity_summary_import",
            "heart_rate_samples",
            "provider_body_energy_source_values",
        ],
    )
    credential_vault_reference_payload = json.dumps(credential_vault_reference)

    assert (
        credential_vault_reference["artifact_kind"]
        == "scout_wearable_provider_live_credential_vault_reference_result"
    )
    assert Path(credential_vault_reference["credential_vault_reference_path"]).exists()
    assert (
        credential_vault_reference["credential_vault_reference"]["transport"][
            "transport_mode"
        ]
        == "credential_vault_reference_only"
    )
    assert (
        credential_vault_reference["credential_vault_reference"]["credential_vault"][
            "credential_values_loaded"
        ]
        is False
    )
    assert "garmin.vault.private" not in credential_vault_reference_payload
    assert "secret-token-value" not in credential_vault_reference_payload
    assert "garmin.account.private" not in credential_vault_reference_payload
    assert "garmin.watch.private" not in credential_vault_reference_payload

    production_gate_with_credentials = write_provider_live_executor_production_readiness_gate(
        lifecycle_audit_path=Path(lifecycle_audit["executor_lifecycle_audit_path"]),
        credential_vault_reference_path=Path(
            credential_vault_reference["credential_vault_reference_path"]
        ),
        output_path=tmp_path / "executor-production-readiness-gate-with-credentials.json",
    )
    production_gate_with_credentials_payload = json.dumps(production_gate_with_credentials)

    assert production_gate_with_credentials["production_provider_execution_ready"] is False
    assert (
        "live_provider_connector_not_implemented"
        in production_gate_with_credentials["production_blockers"]
    )
    assert (
        "credential_vault_not_integrated"
        not in production_gate_with_credentials["production_blockers"]
    )
    assert (
        production_gate_with_credentials["executor_production_readiness_gate"]["readiness"][
            "credential_vault_reference_present"
        ]
        is True
    )
    assert (
        production_gate_with_credentials["executor_production_readiness_gate"]["inputs"][
            "credential_vault_reference"
        ]["credential_values_loaded"]
        is False
    )
    assert (
        production_gate_with_credentials["executor_production_readiness_gate"]["transport"][
            "network_request_performed"
        ]
        is False
    )
    assert "garmin.vault.private" not in production_gate_with_credentials_payload
    assert "secret-token-value" not in production_gate_with_credentials_payload
    assert "garmin.account.private" not in production_gate_with_credentials_payload
    assert "garmin.watch.private" not in production_gate_with_credentials_payload
    assert "/safety/" not in production_gate_with_credentials_payload

    connector_reference = write_provider_live_connector_reference(
        provider="garmin_health_api_live",
        output_path=tmp_path / "connector-reference.json",
        explicit_consent=True,
        connector_kind="garmin_health_api_connector",
        connector_ref="garmin.connector.private",
        connector_version="garmin-connector-0.1.0",
        connector_binary_ref="garmin.connector.binary.private",
        supported_capabilities=[
            "activity_summary_import",
            "heart_rate_samples",
            "provider_body_energy_source_values",
        ],
    )
    connector_reference_payload = json.dumps(connector_reference)

    assert connector_reference["artifact_kind"] == "scout_wearable_provider_live_connector_reference_result"
    assert Path(connector_reference["connector_reference_path"]).exists()
    assert (
        connector_reference["connector_reference"]["connector"][
            "connector_process_started"
        ]
        is False
    )
    assert (
        connector_reference["connector_reference"]["transport"][
            "network_request_performed"
        ]
        is False
    )
    assert "garmin.connector.private" not in connector_reference_payload
    assert "garmin.connector.binary.private" not in connector_reference_payload

    network_policy_reference = write_provider_live_network_policy_reference(
        provider="garmin_health_api_live",
        output_path=tmp_path / "network-policy-reference.json",
        explicit_consent=True,
        policy_ref="garmin.network.policy.private",
        endpoint_ref="garmin.endpoint.private",
        egress_profile_ref="garmin.egress.private",
        tls_profile_ref="garmin.tls.private",
        allowed_capabilities=[
            "activity_summary_import",
            "heart_rate_samples",
            "provider_body_energy_source_values",
        ],
    )
    network_policy_reference_payload = json.dumps(network_policy_reference)

    assert (
        network_policy_reference["artifact_kind"]
        == "scout_wearable_provider_live_network_policy_reference_result"
    )
    assert Path(network_policy_reference["network_policy_reference_path"]).exists()
    assert (
        network_policy_reference["network_policy_reference"]["network_policy"][
            "network_request_performed"
        ]
        is False
    )
    assert (
        network_policy_reference["network_policy_reference"]["network_policy"][
            "network_socket_opened"
        ]
        is False
    )
    assert "garmin.network.policy.private" not in network_policy_reference_payload
    assert "garmin.endpoint.private" not in network_policy_reference_payload
    assert "garmin.egress.private" not in network_policy_reference_payload
    assert "garmin.tls.private" not in network_policy_reference_payload

    runtime_ingest_boundary_reference = write_provider_live_runtime_ingest_boundary_reference(
        provider="garmin_health_api_live",
        output_path=tmp_path / "runtime-ingest-boundary-reference.json",
        explicit_consent=True,
        runtime_boundary_ref="phase1.runtime.boundary.private",
        runtime_channel_ref="energy.advisory.channel.private",
        allowed_artifact_kinds=[
            "scout_wearable_provider_live_executor_production_readiness_gate",
            "scout_energy_reserve_baseline",
        ],
        handoff_mode="advisory_energy_reference_only",
    )
    runtime_ingest_boundary_reference_payload = json.dumps(runtime_ingest_boundary_reference)

    assert (
        runtime_ingest_boundary_reference["artifact_kind"]
        == "scout_wearable_provider_live_runtime_ingest_boundary_reference_result"
    )
    assert Path(
        runtime_ingest_boundary_reference["runtime_ingest_boundary_reference_path"]
    ).exists()
    assert (
        runtime_ingest_boundary_reference["runtime_ingest_boundary_reference"][
            "runtime_ingest_boundary"
        ]["runtime_ingest_authorized"]
        is False
    )
    assert (
        runtime_ingest_boundary_reference["runtime_ingest_boundary_reference"][
            "runtime_ingest_boundary"
        ]["phase1_runtime_safety_truth"]
        is False
    )
    assert "phase1.runtime.boundary.private" not in runtime_ingest_boundary_reference_payload
    assert "energy.advisory.channel.private" not in runtime_ingest_boundary_reference_payload

    phase1_safety_boundary_reference = write_provider_live_phase1_safety_boundary_reference(
        provider="garmin_health_api_live",
        output_path=tmp_path / "phase1-safety-boundary-reference.json",
        explicit_consent=True,
        phase1_boundary_ref="phase1.safety.boundary.private",
        phase1_state_ref="phase1.l0-l4.state.private",
        advisory_channel_ref="energy.advisory.channel.private",
        allowed_artifact_kinds=[
            "scout_wearable_provider_live_executor_production_readiness_gate",
            "scout_energy_reserve_baseline",
        ],
    )
    phase1_safety_boundary_reference_payload = json.dumps(phase1_safety_boundary_reference)

    assert (
        phase1_safety_boundary_reference["artifact_kind"]
        == "scout_wearable_provider_live_phase1_safety_boundary_reference_result"
    )
    assert Path(
        phase1_safety_boundary_reference["phase1_safety_boundary_reference_path"]
    ).exists()
    assert (
        phase1_safety_boundary_reference["phase1_safety_boundary_reference"][
            "phase1_safety_boundary"
        ]["not_safety_truth"]
        is True
    )
    assert (
        phase1_safety_boundary_reference["phase1_safety_boundary_reference"][
            "phase1_safety_boundary"
        ]["phase1_l0_l4_state_mutated"]
        is False
    )
    assert "phase1.safety.boundary.private" not in phase1_safety_boundary_reference_payload
    assert "phase1.l0-l4.state.private" not in phase1_safety_boundary_reference_payload
    assert "energy.advisory.channel.private" not in phase1_safety_boundary_reference_payload

    production_gate_with_refs = write_provider_live_executor_production_readiness_gate(
        lifecycle_audit_path=Path(lifecycle_audit["executor_lifecycle_audit_path"]),
        connector_reference_path=Path(connector_reference["connector_reference_path"]),
        credential_vault_reference_path=Path(
            credential_vault_reference["credential_vault_reference_path"]
        ),
        network_policy_reference_path=Path(
            network_policy_reference["network_policy_reference_path"]
        ),
        runtime_ingest_boundary_reference_path=Path(
            runtime_ingest_boundary_reference["runtime_ingest_boundary_reference_path"]
        ),
        phase1_safety_boundary_reference_path=Path(
            phase1_safety_boundary_reference["phase1_safety_boundary_reference_path"]
        ),
        output_path=tmp_path / "executor-production-readiness-gate-with-refs.json",
    )
    production_gate_with_refs_payload = json.dumps(production_gate_with_refs)

    assert production_gate_with_refs["production_provider_execution_ready"] is False
    assert (
        "live_provider_connector_not_implemented"
        not in production_gate_with_refs["production_blockers"]
    )
    assert "credential_vault_not_integrated" not in production_gate_with_refs["production_blockers"]
    assert "network_execution_disabled_by_local_contract" not in production_gate_with_refs["production_blockers"]
    assert "runtime_ingest_disabled_by_boundary" in production_gate_with_refs["production_blockers"]
    assert (
        "phase1_runtime_safety_truth_mutation_forbidden"
        in production_gate_with_refs["production_blockers"]
    )
    assert (
        production_gate_with_refs["executor_production_readiness_gate"]["readiness"][
            "live_provider_connector_reference_present"
        ]
        is True
    )
    assert (
        production_gate_with_refs["executor_production_readiness_gate"]["readiness"][
            "phase1_safety_boundary_reference_present"
        ]
        is True
    )
    assert (
        production_gate_with_refs["executor_production_readiness_gate"]["readiness"][
            "phase1_runtime_safety_truth"
        ]
        is False
    )
    assert (
        production_gate_with_refs["executor_production_readiness_gate"]["readiness"][
            "phase1_l0_l4_state_mutated"
        ]
        is False
    )
    assert (
        production_gate_with_refs["executor_production_readiness_gate"]["readiness"][
            "safety_api_called"
        ]
        is False
    )
    assert (
        production_gate_with_refs["executor_production_readiness_gate"]["readiness"][
            "runtime_ingest_boundary_reference_present"
        ]
        is True
    )
    assert (
        production_gate_with_refs["executor_production_readiness_gate"]["readiness"][
            "network_policy_reference_present"
        ]
        is True
    )
    assert (
        production_gate_with_refs["executor_production_readiness_gate"]["inputs"][
            "connector_reference"
        ]["connector_process_started"]
        is False
    )
    assert (
        production_gate_with_refs["executor_production_readiness_gate"]["transport"][
            "network_request_performed"
        ]
        is False
    )
    assert (
        production_gate_with_refs["executor_production_readiness_gate"]["inputs"][
            "network_policy_reference"
        ]["network_request_performed"]
        is False
    )
    assert (
        production_gate_with_refs["executor_production_readiness_gate"]["inputs"][
            "runtime_ingest_boundary_reference"
        ]["runtime_ingest_authorized"]
        is False
    )
    assert (
        production_gate_with_refs["executor_production_readiness_gate"]["inputs"][
            "phase1_safety_boundary_reference"
        ]["not_safety_truth"]
        is True
    )
    assert (
        production_gate_with_refs["executor_production_readiness_gate"]["inputs"][
            "phase1_safety_boundary_reference"
        ]["phase1_l0_l4_state_mutated"]
        is False
    )
    assert "garmin.connector.private" not in production_gate_with_refs_payload
    assert "garmin.connector.binary.private" not in production_gate_with_refs_payload
    assert "garmin.network.policy.private" not in production_gate_with_refs_payload
    assert "garmin.endpoint.private" not in production_gate_with_refs_payload
    assert "phase1.runtime.boundary.private" not in production_gate_with_refs_payload
    assert "phase1.safety.boundary.private" not in production_gate_with_refs_payload
    assert "phase1.l0-l4.state.private" not in production_gate_with_refs_payload
    assert "energy.advisory.channel.private" not in production_gate_with_refs_payload
    assert "garmin.vault.private" not in production_gate_with_refs_payload
    assert "secret-token-value" not in production_gate_with_refs_payload
    assert "/safety/" not in production_gate_with_refs_payload

    manifest_admission = write_provider_live_transport_response_admission_from_executor_response_manifest(
        executor_response_manifest_path=Path(response_manifest["executor_response_manifest_path"]),
        output_dir=tmp_path / "manifest-sanitized",
        activity_id_prefix="live.garmin.manifest.admitted",
        admitted_capabilities=["activity_summary_import", "provider_body_energy_source_values"],
        admission_output_path=tmp_path / "manifest-admission.json",
    )
    manifest_admission_payload = json.dumps(manifest_admission)

    assert (
        manifest_admission["artifact_kind"]
        == "scout_wearable_provider_live_executor_response_manifest_admission_result"
    )
    assert manifest_admission["source_provider"] == "garmin_health_api_live"
    assert (
        manifest_admission["executor_response_manifest"]["sha256"]
        == response_manifest["executor_response_manifest"]["sha256"]
    )
    assert manifest_admission["admission"]["sanitized_import_result"]["activity_count"] == 2
    assert all(Path(path).exists() for path in manifest_admission["sanitized_import_paths"])
    assert manifest_admission["transport"]["transport_mode"] == "executor_response_manifest_admission_only"
    assert manifest_admission["transport"]["network_request_performed"] is False
    assert manifest_admission["transport"]["real_provider_api_called"] is False
    assert manifest_admission["transport"]["runtime_ingest_performed"] is False
    assert "heartRateSamples" not in manifest_admission_payload
    assert "geoPolylineDTO" not in manifest_admission_payload
    assert "local.garmin.executor.private" not in manifest_admission_payload
    assert "secret-token-value" not in manifest_admission_payload
    assert "garmin.account.private" not in manifest_admission_payload
    assert "garmin.watch.private" not in manifest_admission_payload
    assert "/safety/" not in manifest_admission_payload

    replay = write_provider_live_executor_fixture_replay(
        request_plan_path=Path(result["request_plan_path"]),
        executor_registration_path=Path(registration["executor_registration_path"]),
        response_fixture_path=response_fixture_path,
        output_path=tmp_path / "executor-fixture-replay.json",
    )
    replay_payload = json.dumps(replay)

    assert replay["artifact_kind"] == "scout_wearable_provider_live_executor_fixture_replay_result"
    assert replay["executor_fixture_replay"]["artifact_kind"] == "scout_wearable_provider_live_executor_fixture_replay"
    assert replay["executor_fixture_replay"]["source_provider"] == "garmin_health_api_live"
    assert replay["executor_fixture_replay"]["readiness"]["execution_blockers"] == [
        "network_execution_disabled_by_local_contract"
    ]
    assert replay["executor_fixture_replay"]["response_fixture"]["raw_response_embedded"] is False
    assert replay["executor_fixture_replay"]["transport"]["transport_mode"] == "executor_fixture_replay_only"
    assert replay["executor_fixture_replay"]["transport"]["network_request_performed"] is False
    assert replay["executor_fixture_replay"]["transport"]["real_provider_api_called"] is False
    assert replay["executor_fixture_replay"]["transport"]["runtime_ingest_performed"] is False
    assert replay["executor_fixture_replay"]["mutation"]["safety_api_called"] is False
    assert Path(replay["executor_fixture_replay_path"]).exists()
    assert "heartRateSamples" not in replay_payload
    assert "geoPolylineDTO" not in replay_payload
    assert "local.garmin.executor.private" not in replay_payload
    assert "secret-token-value" not in replay_payload
    assert "garmin.account.private" not in replay_payload
    assert "garmin.watch.private" not in replay_payload
    assert "/safety/" not in replay_payload

    replay_admission = write_provider_live_transport_response_admission_from_fixture_replay(
        fixture_replay_path=Path(handoff_replay["executor_fixture_replay_path"]),
        output_dir=tmp_path / "replay-sanitized",
        activity_id_prefix="live.garmin.replay.admitted",
        admitted_capabilities=["activity_summary_import", "provider_body_energy_source_values"],
        admission_output_path=tmp_path / "replay-admission.json",
    )
    replay_admission_payload = json.dumps(replay_admission)

    assert replay_admission["artifact_kind"] == "scout_wearable_provider_live_executor_replay_admission_result"
    assert replay_admission["source_provider"] == "garmin_health_api_live"
    assert (
        replay_admission["executor_fixture_replay"]["sha256"]
        == handoff_replay["executor_fixture_replay"]["sha256"]
    )
    assert replay_admission["admission"]["artifact_kind"] == "scout_wearable_provider_live_transport_response_admission"
    assert replay_admission["admission"]["sanitized_import_result"]["activity_count"] == 2
    assert all(Path(path).exists() for path in replay_admission["sanitized_import_paths"])
    assert replay_admission["transport"]["transport_mode"] == "executor_replay_admission_only"
    assert replay_admission["transport"]["network_request_performed"] is False
    assert replay_admission["transport"]["real_provider_api_called"] is False
    assert replay_admission["transport"]["runtime_ingest_performed"] is False
    assert replay_admission["mutation"]["safety_api_called"] is False
    assert "heartRateSamples" not in replay_admission_payload
    assert "geoPolylineDTO" not in replay_admission_payload
    assert "local.garmin.executor.private" not in replay_admission_payload
    assert "secret-token-value" not in replay_admission_payload
    assert "garmin.account.private" not in replay_admission_payload
    assert "garmin.watch.private" not in replay_admission_payload
    assert "/safety/" not in replay_admission_payload


def test_provider_live_transport_request_plan_rejects_unapproved_capability(tmp_path):
    preflight_result = write_provider_live_transport_preflight(
        provider="apple_healthkit_live",
        output_path=tmp_path / "preflight.json",
        explicit_consent=True,
        account_ref="apple.health.account.private",
        auth_token_ref="healthkit-grant-ref",
        scopes=["HKWorkoutType"],
        requested_capabilities=["activity_summary_import"],
    )

    try:
        build_provider_live_transport_request_plan(
            preflight_path=Path(preflight_result["preflight_path"]),
            window_start_date="2026-05-20",
            window_end_date="2026-05-27",
            requested_capabilities=["heart_rate_samples"],
        )
    except ValueError as exc:
        assert "not allowed by provider live transport preflight" in str(exc)
    else:
        raise AssertionError("request plan should reject capabilities not allowed by preflight")


def test_provider_live_transport_request_plan_cli_writes_apple_descriptor_only(tmp_path):
    preflight_result = write_provider_live_transport_preflight(
        provider="apple_healthkit_live",
        output_path=tmp_path / "apple-preflight.json",
        explicit_consent=True,
        account_ref="apple.health.account.private",
        device_ref="apple.watch.private",
        auth_token_ref="healthkit-grant-ref",
        scopes=["HKWorkoutType", "HKQuantityTypeIdentifierHeartRate"],
        requested_capabilities=["activity_summary_import", "heart_rate_samples"],
    )
    output_path = tmp_path / "apple-request-plan.json"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scout_energy_reserve",
            "provider-live-request-plan",
            "--preflight",
            preflight_result["preflight_path"],
            "--output",
            str(output_path),
            "--window-start-date",
            "2026-05-20",
            "--window-end-date",
            "2026-05-27",
            "--capability",
            "activity_summary_import",
            "--capability",
            "heart_rate_samples",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(completed.stdout)
    plan = json.loads(output_path.read_text(encoding="utf-8"))
    serialized = completed.stdout + output_path.read_text(encoding="utf-8")

    assert payload["artifact_kind"] == "scout_wearable_provider_live_transport_request_plan_result"
    assert plan["source_provider"] == "apple_healthkit_live"
    assert [slot["provider_request_kind"] for slot in plan["request_slots"]] == [
        "apple_healthkit_workout_query",
        "apple_healthkit_heart_rate_summary_query",
    ]
    assert all(slot["provider_endpoint_ref"].startswith("apple_healthkit.") for slot in plan["request_slots"])
    assert plan["transport"]["network_request_performed"] is False
    assert plan["transport"]["real_provider_api_called"] is False
    assert plan["transport"]["runtime_ingest_performed"] is False
    assert plan["mutation"]["raw_health_payload_shared"] is False
    assert plan["boundary"]["phase1_runtime_safety_truth"] is False
    assert "HKWorkoutType" not in serialized
    assert "HKQuantityTypeIdentifierHeartRate" not in serialized
    assert "healthkit-grant-ref" not in serialized
    assert "apple.health.account.private" not in serialized
    assert "/safety/" not in serialized

    readiness_output_path = tmp_path / "apple-executor-readiness.json"
    readiness_completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scout_energy_reserve",
            "provider-live-executor-readiness",
            "--request-plan",
            str(output_path),
            "--output",
            str(readiness_output_path),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    readiness_payload = json.loads(readiness_completed.stdout)
    readiness_artifact = json.loads(readiness_output_path.read_text(encoding="utf-8"))
    readiness_serialized = readiness_completed.stdout + readiness_output_path.read_text(encoding="utf-8")

    assert readiness_payload["artifact_kind"] == "scout_wearable_provider_live_executor_readiness_result"
    assert readiness_artifact["source_provider"] == "apple_healthkit_live"
    assert readiness_artifact["ready_for_live_execution"] is False
    assert readiness_artifact["transport"]["transport_mode"] == "executor_readiness_only"
    assert readiness_artifact["transport"]["network_request_performed"] is False
    assert readiness_artifact["transport"]["real_provider_api_called"] is False
    assert readiness_artifact["transport"]["runtime_ingest_performed"] is False
    assert readiness_artifact["privacy"]["raw_health_payload_shared"] is False
    assert readiness_artifact["boundary"]["phase1_runtime_safety_truth"] is False
    assert "HKWorkoutType" not in readiness_serialized
    assert "HKQuantityTypeIdentifierHeartRate" not in readiness_serialized
    assert "healthkit-grant-ref" not in readiness_serialized
    assert "apple.health.account.private" not in readiness_serialized
    assert "/safety/" not in readiness_serialized

    registration_output_path = tmp_path / "apple-executor-registration.json"
    registration_completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scout_energy_reserve",
            "provider-live-register-executor",
            "--preflight",
            preflight_result["preflight_path"],
            "--output",
            str(registration_output_path),
            "--executor-kind",
            "apple_healthkit_local_bridge",
            "--executor-ref",
            "apple.local.executor.private",
            "--capability",
            "activity_summary_import",
            "--capability",
            "heart_rate_samples",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    registration_payload = json.loads(registration_completed.stdout)
    registration_artifact = json.loads(registration_output_path.read_text(encoding="utf-8"))
    registration_serialized = registration_completed.stdout + registration_output_path.read_text(encoding="utf-8")

    assert registration_payload["artifact_kind"] == "scout_wearable_provider_live_executor_registration_result"
    assert registration_artifact["source_provider"] == "apple_healthkit_live"
    assert registration_artifact["executor_registration"]["executor_registered"] is True
    assert registration_artifact["executor_registration"]["executor_ref_exposed"] is False
    assert registration_artifact["transport"]["network_request_performed"] is False
    assert registration_artifact["transport"]["real_provider_api_called"] is False
    assert registration_artifact["transport"]["runtime_ingest_performed"] is False
    assert "apple.local.executor.private" not in registration_serialized
    assert "HKWorkoutType" not in registration_serialized
    assert "HKQuantityTypeIdentifierHeartRate" not in registration_serialized
    assert "healthkit-grant-ref" not in registration_serialized
    assert "apple.health.account.private" not in registration_serialized
    assert "/safety/" not in registration_serialized

    handoff_output_path = tmp_path / "apple-executor-handoff.json"
    handoff_completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scout_energy_reserve",
            "provider-live-executor-handoff",
            "--request-plan",
            str(output_path),
            "--executor-registration",
            str(registration_output_path),
            "--output",
            str(handoff_output_path),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    handoff_payload = json.loads(handoff_completed.stdout)
    handoff_artifact = json.loads(handoff_output_path.read_text(encoding="utf-8"))
    handoff_serialized = handoff_completed.stdout + handoff_output_path.read_text(encoding="utf-8")

    assert handoff_payload["artifact_kind"] == "scout_wearable_provider_live_executor_handoff_package_result"
    assert handoff_artifact["source_provider"] == "apple_healthkit_live"
    assert handoff_artifact["request_descriptor_count"] == 2
    assert handoff_artifact["transport"]["request_executor_bound"] is False
    assert handoff_artifact["transport"]["network_request_performed"] is False
    assert handoff_artifact["transport"]["real_provider_api_called"] is False
    assert handoff_artifact["transport"]["runtime_ingest_performed"] is False
    assert "apple.local.executor.private" not in handoff_serialized
    assert "HKWorkoutType" not in handoff_serialized
    assert "HKQuantityTypeIdentifierHeartRate" not in handoff_serialized
    assert "healthkit-grant-ref" not in handoff_serialized
    assert "apple.health.account.private" not in handoff_serialized
    assert "/safety/" not in handoff_serialized

    handoff_outbox_dir = tmp_path / "apple-executor-handoff-outbox"
    handoff_outbox_dir.mkdir()
    (handoff_outbox_dir / "apple-executor-handoff.json").write_text(
        handoff_output_path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (handoff_outbox_dir / "unrelated.json").write_text(
        json.dumps({"artifact_kind": "unrelated_local_artifact"}),
        encoding="utf-8",
    )
    handoff_outbox_index_output_path = tmp_path / "apple-executor-handoff-outbox-index.json"
    handoff_outbox_index_completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scout_energy_reserve",
            "provider-live-index-executor-handoff-outbox",
            "--outbox-dir",
            str(handoff_outbox_dir),
            "--output",
            str(handoff_outbox_index_output_path),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    handoff_outbox_index_payload = json.loads(handoff_outbox_index_completed.stdout)
    handoff_outbox_index_artifact = json.loads(
        handoff_outbox_index_output_path.read_text(encoding="utf-8")
    )
    handoff_outbox_index_serialized = (
        handoff_outbox_index_completed.stdout
        + handoff_outbox_index_output_path.read_text(encoding="utf-8")
    )

    assert (
        handoff_outbox_index_payload["artifact_kind"]
        == "scout_wearable_provider_live_executor_handoff_outbox_index_result"
    )
    assert handoff_outbox_index_artifact["source_provider"] == "apple_healthkit_live"
    assert handoff_outbox_index_artifact["outbox"]["json_file_count"] == 2
    assert handoff_outbox_index_artifact["outbox"]["eligible_handoff_count"] == 1
    assert handoff_outbox_index_artifact["transport"]["network_request_performed"] is False
    assert handoff_outbox_index_artifact["transport"]["real_provider_api_called"] is False
    assert handoff_outbox_index_artifact["transport"]["runtime_ingest_performed"] is False
    assert "apple.local.executor.private" not in handoff_outbox_index_serialized
    assert "HKWorkoutType" not in handoff_outbox_index_serialized
    assert "HKQuantityTypeIdentifierHeartRate" not in handoff_outbox_index_serialized
    assert "healthkit-grant-ref" not in handoff_outbox_index_serialized
    assert "apple.health.account.private" not in handoff_outbox_index_serialized
    assert "/safety/" not in handoff_outbox_index_serialized

    handoff_pickup_output_path = tmp_path / "apple-executor-handoff-pickup-manifest.json"
    handoff_pickup_completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scout_energy_reserve",
            "provider-live-executor-handoff-pickup-manifest",
            "--outbox-index",
            str(handoff_outbox_index_output_path),
            "--output",
            str(handoff_pickup_output_path),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    handoff_pickup_payload = json.loads(handoff_pickup_completed.stdout)
    handoff_pickup_artifact = json.loads(
        handoff_pickup_output_path.read_text(encoding="utf-8")
    )
    handoff_pickup_serialized = (
        handoff_pickup_completed.stdout
        + handoff_pickup_output_path.read_text(encoding="utf-8")
    )

    assert (
        handoff_pickup_payload["artifact_kind"]
        == "scout_wearable_provider_live_executor_handoff_pickup_manifest_result"
    )
    assert handoff_pickup_artifact["source_provider"] == "apple_healthkit_live"
    assert handoff_pickup_artifact["pickup"]["pickup_status"] == "ready_for_external_executor_review"
    assert handoff_pickup_artifact["pickup"]["external_execution_authorized"] is False
    assert handoff_pickup_artifact["transport"]["network_request_performed"] is False
    assert handoff_pickup_artifact["transport"]["real_provider_api_called"] is False
    assert handoff_pickup_artifact["transport"]["runtime_ingest_performed"] is False
    assert "apple.local.executor.private" not in handoff_pickup_serialized
    assert "HKWorkoutType" not in handoff_pickup_serialized
    assert "HKQuantityTypeIdentifierHeartRate" not in handoff_pickup_serialized
    assert "healthkit-grant-ref" not in handoff_pickup_serialized
    assert "apple.health.account.private" not in handoff_pickup_serialized
    assert "/safety/" not in handoff_pickup_serialized

    apple_response_fixture_path = _write_apple_healthkit_response_fixture(tmp_path / "apple-response.json")
    pickup_response_manifest_output_path = tmp_path / "apple-executor-pickup-response-manifest.json"
    pickup_response_manifest_completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scout_energy_reserve",
            "provider-live-executor-pickup-response-manifest",
            "--pickup-manifest",
            str(handoff_pickup_output_path),
            "--response-payload",
            str(apple_response_fixture_path),
            "--output",
            str(pickup_response_manifest_output_path),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    pickup_response_manifest_payload = json.loads(pickup_response_manifest_completed.stdout)
    pickup_response_manifest_artifact = json.loads(
        pickup_response_manifest_output_path.read_text(encoding="utf-8")
    )
    pickup_response_manifest_serialized = (
        pickup_response_manifest_completed.stdout
        + pickup_response_manifest_output_path.read_text(encoding="utf-8")
    )

    assert (
        pickup_response_manifest_payload["artifact_kind"]
        == "scout_wearable_provider_live_executor_pickup_response_manifest_result"
    )
    assert pickup_response_manifest_artifact["source_provider"] == "apple_healthkit_live"
    assert pickup_response_manifest_artifact["pickup_manifest"]["sha256"] == handoff_pickup_artifact["sha256"]
    assert pickup_response_manifest_artifact["pickup_manifest"]["external_execution_authorized"] is False
    assert pickup_response_manifest_artifact["transport"]["network_request_performed"] is False
    assert pickup_response_manifest_artifact["transport"]["real_provider_api_called"] is False
    assert pickup_response_manifest_artifact["transport"]["runtime_ingest_performed"] is False
    assert "apple.local.executor.private" not in pickup_response_manifest_serialized
    assert "HKWorkoutType" not in pickup_response_manifest_serialized
    assert "HKQuantityTypeIdentifierHeartRate" not in pickup_response_manifest_serialized
    assert "healthkit-grant-ref" not in pickup_response_manifest_serialized
    assert "apple.health.account.private" not in pickup_response_manifest_serialized
    assert "/safety/" not in pickup_response_manifest_serialized

    pickup_response_consumption_output_dir = tmp_path / "apple-pickup-response-consumption"
    pickup_response_consumption_completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scout_energy_reserve",
            "provider-live-consume-executor-pickup-response",
            "--executor-response-manifest",
            str(pickup_response_manifest_output_path),
            "--output-dir",
            str(pickup_response_consumption_output_dir),
            "--activity-id-prefix",
            "live.apple.executor.pickup.response.consumed",
            "--capability",
            "activity_summary_import",
            "--capability",
            "heart_rate_samples",
            "--reference-date",
            "2026-05-27",
            "--root",
            str(tmp_path),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    pickup_response_consumption_payload = json.loads(pickup_response_consumption_completed.stdout)
    pickup_response_consumption_artifact = json.loads(
        (
            pickup_response_consumption_output_dir
            / "provider_live_executor_pickup_response_consumption.json"
        ).read_text(encoding="utf-8")
    )
    pickup_response_consumption_serialized = (
        pickup_response_consumption_completed.stdout
        + (
            pickup_response_consumption_output_dir
            / "provider_live_executor_pickup_response_consumption.json"
        ).read_text(encoding="utf-8")
    )

    assert (
        pickup_response_consumption_payload["artifact_kind"]
        == "scout_wearable_provider_live_executor_pickup_response_consumption_result"
    )
    assert Path(pickup_response_consumption_payload["baseline_path"]).exists()
    assert pickup_response_consumption_artifact["source_provider"] == "apple_healthkit_live"
    assert pickup_response_consumption_artifact["pickup_manifest"]["sha256"] == handoff_pickup_artifact["sha256"]
    assert Path(
        pickup_response_consumption_artifact["executor_response_consumption"]["baseline_path"]
    ).exists()
    assert pickup_response_consumption_artifact["transport"]["network_request_performed"] is False
    assert pickup_response_consumption_artifact["transport"]["real_provider_api_called"] is False
    assert pickup_response_consumption_artifact["transport"]["runtime_ingest_performed"] is False
    assert "apple.local.executor.private" not in pickup_response_consumption_serialized
    assert "HKWorkoutType" not in pickup_response_consumption_serialized
    assert "HKQuantityTypeIdentifierHeartRate" not in pickup_response_consumption_serialized
    assert "healthkit-grant-ref" not in pickup_response_consumption_serialized
    assert "apple.health.account.private" not in pickup_response_consumption_serialized
    assert "/safety/" not in pickup_response_consumption_serialized

    pickup_response_receipt_output_path = tmp_path / "apple-pickup-response-consumption-receipt.json"
    pickup_response_receipt_completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scout_energy_reserve",
            "provider-live-executor-pickup-response-consumption-receipt",
            "--pickup-response-consumption",
            str(
                pickup_response_consumption_output_dir
                / "provider_live_executor_pickup_response_consumption.json"
            ),
            "--output",
            str(pickup_response_receipt_output_path),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    pickup_response_receipt_payload = json.loads(pickup_response_receipt_completed.stdout)
    pickup_response_receipt_artifact = json.loads(
        pickup_response_receipt_output_path.read_text(encoding="utf-8")
    )
    pickup_response_receipt_serialized = (
        pickup_response_receipt_completed.stdout
        + pickup_response_receipt_output_path.read_text(encoding="utf-8")
    )

    assert (
        pickup_response_receipt_payload["artifact_kind"]
        == "scout_wearable_provider_live_executor_pickup_response_consumption_receipt_result"
    )
    assert pickup_response_receipt_artifact["source_provider"] == "apple_healthkit_live"
    assert (
        pickup_response_receipt_artifact["pickup_response_consumption"]["sha256"]
        == pickup_response_consumption_artifact["sha256"]
    )
    assert pickup_response_receipt_artifact["pickup_manifest"]["sha256"] == handoff_pickup_artifact["sha256"]
    assert pickup_response_receipt_artifact["receipt"]["receipt_status"] == "locally_recorded"
    assert pickup_response_receipt_artifact["transport"]["network_request_performed"] is False
    assert pickup_response_receipt_artifact["transport"]["real_provider_api_called"] is False
    assert pickup_response_receipt_artifact["transport"]["runtime_ingest_performed"] is False
    assert "apple.local.executor.private" not in pickup_response_receipt_serialized
    assert "HKWorkoutType" not in pickup_response_receipt_serialized
    assert "HKQuantityTypeIdentifierHeartRate" not in pickup_response_receipt_serialized
    assert "healthkit-grant-ref" not in pickup_response_receipt_serialized
    assert "apple.health.account.private" not in pickup_response_receipt_serialized
    assert "/safety/" not in pickup_response_receipt_serialized

    pickup_status_snapshot_output_path = tmp_path / "apple-pickup-status-snapshot.json"
    pickup_status_snapshot_completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scout_energy_reserve",
            "provider-live-executor-pickup-status-snapshot",
            "--pickup-manifest",
            str(handoff_pickup_output_path),
            "--executor-response-manifest",
            str(pickup_response_manifest_output_path),
            "--pickup-response-consumption",
            str(
                pickup_response_consumption_output_dir
                / "provider_live_executor_pickup_response_consumption.json"
            ),
            "--pickup-response-receipt",
            str(pickup_response_receipt_output_path),
            "--output",
            str(pickup_status_snapshot_output_path),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    pickup_status_snapshot_payload = json.loads(pickup_status_snapshot_completed.stdout)
    pickup_status_snapshot_artifact = json.loads(
        pickup_status_snapshot_output_path.read_text(encoding="utf-8")
    )
    pickup_status_snapshot_serialized = (
        pickup_status_snapshot_completed.stdout
        + pickup_status_snapshot_output_path.read_text(encoding="utf-8")
    )

    assert (
        pickup_status_snapshot_payload["artifact_kind"]
        == "scout_wearable_provider_live_executor_pickup_status_snapshot_result"
    )
    assert pickup_status_snapshot_payload["pickup_lifecycle_status"] == "receipt_recorded"
    assert pickup_status_snapshot_artifact["source_provider"] == "apple_healthkit_live"
    assert pickup_status_snapshot_artifact["status"]["local_evidence_complete"] is True
    assert pickup_status_snapshot_artifact["pickup_manifest"]["sha256"] == handoff_pickup_artifact["sha256"]
    assert (
        pickup_status_snapshot_artifact["pickup_response_receipt"]["sha256"]
        == pickup_response_receipt_artifact["sha256"]
    )
    assert pickup_status_snapshot_artifact["transport"]["network_request_performed"] is False
    assert pickup_status_snapshot_artifact["transport"]["real_provider_api_called"] is False
    assert pickup_status_snapshot_artifact["transport"]["runtime_ingest_performed"] is False
    assert "apple.local.executor.private" not in pickup_status_snapshot_serialized
    assert "HKWorkoutType" not in pickup_status_snapshot_serialized
    assert "HKQuantityTypeIdentifierHeartRate" not in pickup_status_snapshot_serialized
    assert "healthkit-grant-ref" not in pickup_status_snapshot_serialized
    assert "apple.health.account.private" not in pickup_status_snapshot_serialized
    assert "/safety/" not in pickup_status_snapshot_serialized

    handoff_replay_output_path = tmp_path / "apple-handoff-fixture-replay.json"
    handoff_replay_completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scout_energy_reserve",
            "provider-live-handoff-fixture-replay",
            "--executor-handoff",
            str(handoff_output_path),
            "--response-fixture",
            str(apple_response_fixture_path),
            "--output",
            str(handoff_replay_output_path),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    handoff_replay_payload = json.loads(handoff_replay_completed.stdout)
    handoff_replay_artifact = json.loads(handoff_replay_output_path.read_text(encoding="utf-8"))
    handoff_replay_serialized = (
        handoff_replay_completed.stdout + handoff_replay_output_path.read_text(encoding="utf-8")
    )

    assert (
        handoff_replay_payload["artifact_kind"]
        == "scout_wearable_provider_live_executor_handoff_fixture_replay_result"
    )
    assert handoff_replay_artifact["source_provider"] == "apple_healthkit_live"
    assert handoff_replay_artifact["handoff_package"]["sha256"] == handoff_artifact["sha256"]
    assert handoff_replay_artifact["response_fixture"]["raw_response_embedded"] is False
    assert handoff_replay_artifact["transport"]["network_request_performed"] is False
    assert handoff_replay_artifact["transport"]["real_provider_api_called"] is False
    assert handoff_replay_artifact["transport"]["runtime_ingest_performed"] is False
    assert "apple.local.executor.private" not in handoff_replay_serialized
    assert "HKWorkoutType" not in handoff_replay_serialized
    assert "HKQuantityTypeIdentifierHeartRate" not in handoff_replay_serialized
    assert "healthkit-grant-ref" not in handoff_replay_serialized
    assert "apple.health.account.private" not in handoff_replay_serialized
    assert "/safety/" not in handoff_replay_serialized

    response_manifest_output_path = tmp_path / "apple-executor-response-manifest.json"
    response_manifest_completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scout_energy_reserve",
            "provider-live-executor-response-manifest",
            "--executor-handoff",
            str(handoff_output_path),
            "--response-payload",
            str(apple_response_fixture_path),
            "--output",
            str(response_manifest_output_path),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    response_manifest_payload = json.loads(response_manifest_completed.stdout)
    response_manifest_artifact = json.loads(response_manifest_output_path.read_text(encoding="utf-8"))
    response_manifest_serialized = (
        response_manifest_completed.stdout + response_manifest_output_path.read_text(encoding="utf-8")
    )

    assert response_manifest_payload["artifact_kind"] == "scout_wearable_provider_live_executor_response_manifest_result"
    assert response_manifest_artifact["source_provider"] == "apple_healthkit_live"
    assert response_manifest_artifact["handoff_package"]["sha256"] == handoff_artifact["sha256"]
    assert response_manifest_artifact["response_payload"]["raw_response_embedded"] is False
    assert response_manifest_artifact["transport"]["network_request_performed"] is False
    assert response_manifest_artifact["transport"]["real_provider_api_called"] is False
    assert response_manifest_artifact["transport"]["runtime_ingest_performed"] is False
    assert "apple.local.executor.private" not in response_manifest_serialized
    assert "HKWorkoutType" not in response_manifest_serialized
    assert "HKQuantityTypeIdentifierHeartRate" not in response_manifest_serialized
    assert "healthkit-grant-ref" not in response_manifest_serialized
    assert "apple.health.account.private" not in response_manifest_serialized
    assert "/safety/" not in response_manifest_serialized

    apple_inbox_dir = tmp_path / "apple-executor-response-inbox"
    apple_inbox_dir.mkdir()
    (apple_inbox_dir / "apple-response-manifest.json").write_text(
        response_manifest_output_path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    inbox_index_output_path = tmp_path / "apple-executor-response-inbox-index.json"
    inbox_index_completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scout_energy_reserve",
            "provider-live-index-executor-response-inbox",
            "--inbox-dir",
            str(apple_inbox_dir),
            "--output",
            str(inbox_index_output_path),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    inbox_index_payload = json.loads(inbox_index_completed.stdout)
    inbox_index_artifact = json.loads(inbox_index_output_path.read_text(encoding="utf-8"))
    inbox_index_serialized = inbox_index_completed.stdout + inbox_index_output_path.read_text(encoding="utf-8")

    assert inbox_index_payload["artifact_kind"] == "scout_wearable_provider_live_executor_response_inbox_index_result"
    assert inbox_index_artifact["source_provider"] == "apple_healthkit_live"
    assert inbox_index_artifact["inbox"]["eligible_manifest_count"] == 1
    assert inbox_index_artifact["manifests"][0]["eligible_for_consumption_precheck"] is True
    assert inbox_index_artifact["manifests"][0]["handoff_ref_valid"] is True
    assert inbox_index_artifact["manifests"][0]["response_payload_ref_valid"] is True
    assert inbox_index_artifact["transport"]["network_request_performed"] is False
    assert inbox_index_artifact["transport"]["real_provider_api_called"] is False
    assert inbox_index_artifact["transport"]["runtime_ingest_performed"] is False
    assert "apple.local.executor.private" not in inbox_index_serialized
    assert "HKWorkoutType" not in inbox_index_serialized
    assert "HKQuantityTypeIdentifierHeartRate" not in inbox_index_serialized
    assert "healthkit-grant-ref" not in inbox_index_serialized
    assert "apple.health.account.private" not in inbox_index_serialized
    assert "/safety/" not in inbox_index_serialized

    inbox_consumption_output_dir = tmp_path / "apple-executor-response-inbox-consumption"
    inbox_consumption_completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scout_energy_reserve",
            "provider-live-consume-executor-response-inbox",
            "--inbox-index",
            str(inbox_index_output_path),
            "--output-dir",
            str(inbox_consumption_output_dir),
            "--activity-id-prefix",
            "live.apple.executor.response.inbox.consumed",
            "--capability",
            "activity_summary_import",
            "--capability",
            "heart_rate_samples",
            "--reference-date",
            "2026-05-27",
            "--root",
            str(tmp_path),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    inbox_consumption_payload = json.loads(inbox_consumption_completed.stdout)
    inbox_consumption_artifact = json.loads(
        (inbox_consumption_output_dir / "provider_live_executor_response_inbox_consumption.json").read_text(
            encoding="utf-8"
        )
    )
    inbox_consumption_serialized = (
        inbox_consumption_completed.stdout
        + (inbox_consumption_output_dir / "provider_live_executor_response_inbox_consumption.json").read_text(
            encoding="utf-8"
        )
    )

    assert (
        inbox_consumption_payload["artifact_kind"]
        == "scout_wearable_provider_live_executor_response_inbox_consumption_result"
    )
    assert inbox_consumption_artifact["source_provider"] == "apple_healthkit_live"
    assert inbox_consumption_artifact["selected_manifest"]["source_path"] == str(
        apple_inbox_dir / "apple-response-manifest.json"
    )
    assert Path(inbox_consumption_payload["baseline_path"]).exists()
    assert inbox_consumption_artifact["transport"]["network_request_performed"] is False
    assert inbox_consumption_artifact["transport"]["real_provider_api_called"] is False
    assert inbox_consumption_artifact["transport"]["runtime_ingest_performed"] is False
    assert "apple.local.executor.private" not in inbox_consumption_serialized
    assert "HKWorkoutType" not in inbox_consumption_serialized
    assert "HKQuantityTypeIdentifierHeartRate" not in inbox_consumption_serialized
    assert "healthkit-grant-ref" not in inbox_consumption_serialized
    assert "apple.health.account.private" not in inbox_consumption_serialized
    assert "/safety/" not in inbox_consumption_serialized

    inbox_batch_consumption_output_dir = tmp_path / "apple-executor-response-inbox-batch-consumption"
    inbox_batch_consumption_completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scout_energy_reserve",
            "provider-live-consume-executor-response-inbox-batch",
            "--inbox-index",
            str(inbox_index_output_path),
            "--output-dir",
            str(inbox_batch_consumption_output_dir),
            "--activity-id-prefix",
            "live.apple.executor.response.inbox.batch.consumed",
            "--capability",
            "activity_summary_import",
            "--capability",
            "heart_rate_samples",
            "--reference-date",
            "2026-05-27",
            "--root",
            str(tmp_path),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    inbox_batch_consumption_payload = json.loads(inbox_batch_consumption_completed.stdout)
    inbox_batch_consumption_artifact = json.loads(
        (
            inbox_batch_consumption_output_dir
            / "provider_live_executor_response_inbox_batch_consumption.json"
        ).read_text(encoding="utf-8")
    )
    inbox_batch_consumption_serialized = (
        inbox_batch_consumption_completed.stdout
        + (
            inbox_batch_consumption_output_dir
            / "provider_live_executor_response_inbox_batch_consumption.json"
        ).read_text(encoding="utf-8")
    )

    assert (
        inbox_batch_consumption_payload["artifact_kind"]
        == "scout_wearable_provider_live_executor_response_inbox_batch_consumption_result"
    )
    assert inbox_batch_consumption_payload["consumed_manifest_count"] == 1
    assert inbox_batch_consumption_artifact["source_provider"] == "apple_healthkit_live"
    assert inbox_batch_consumption_artifact["batch"]["consumed_manifest_count"] == 1
    assert inbox_batch_consumption_artifact["transport"]["network_request_performed"] is False
    assert inbox_batch_consumption_artifact["transport"]["real_provider_api_called"] is False
    assert inbox_batch_consumption_artifact["transport"]["runtime_ingest_performed"] is False
    assert "apple.local.executor.private" not in inbox_batch_consumption_serialized
    assert "HKWorkoutType" not in inbox_batch_consumption_serialized
    assert "HKQuantityTypeIdentifierHeartRate" not in inbox_batch_consumption_serialized
    assert "healthkit-grant-ref" not in inbox_batch_consumption_serialized
    assert "apple.health.account.private" not in inbox_batch_consumption_serialized
    assert "/safety/" not in inbox_batch_consumption_serialized

    inbox_batch_receipt_output_path = tmp_path / "apple-executor-response-inbox-batch-receipt.json"
    inbox_batch_receipt_completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scout_energy_reserve",
            "provider-live-executor-response-inbox-batch-receipt",
            "--batch-consumption",
            str(
                inbox_batch_consumption_output_dir
                / "provider_live_executor_response_inbox_batch_consumption.json"
            ),
            "--output",
            str(inbox_batch_receipt_output_path),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    inbox_batch_receipt_payload = json.loads(inbox_batch_receipt_completed.stdout)
    inbox_batch_receipt_artifact = json.loads(
        inbox_batch_receipt_output_path.read_text(encoding="utf-8")
    )
    inbox_batch_receipt_serialized = (
        inbox_batch_receipt_completed.stdout
        + inbox_batch_receipt_output_path.read_text(encoding="utf-8")
    )

    assert (
        inbox_batch_receipt_payload["artifact_kind"]
        == "scout_wearable_provider_live_executor_response_inbox_batch_receipt_result"
    )
    assert inbox_batch_receipt_payload["consumed_manifest_count"] == 1
    assert inbox_batch_receipt_artifact["source_provider"] == "apple_healthkit_live"
    assert inbox_batch_receipt_artifact["batch_consumption"]["consumed_manifest_count"] == 1
    assert inbox_batch_receipt_artifact["transport"]["network_request_performed"] is False
    assert inbox_batch_receipt_artifact["transport"]["real_provider_api_called"] is False
    assert inbox_batch_receipt_artifact["transport"]["runtime_ingest_performed"] is False
    assert inbox_batch_receipt_artifact["receipts"][0]["receipt_status"] == "locally_recorded"
    assert "apple.local.executor.private" not in inbox_batch_receipt_serialized
    assert "HKWorkoutType" not in inbox_batch_receipt_serialized
    assert "HKQuantityTypeIdentifierHeartRate" not in inbox_batch_receipt_serialized
    assert "healthkit-grant-ref" not in inbox_batch_receipt_serialized
    assert "apple.health.account.private" not in inbox_batch_receipt_serialized
    assert "/safety/" not in inbox_batch_receipt_serialized

    inbox_status_snapshot_output_path = tmp_path / "apple-executor-response-inbox-status-snapshot.json"
    inbox_status_snapshot_completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scout_energy_reserve",
            "provider-live-executor-response-inbox-status-snapshot",
            "--inbox-index",
            str(inbox_index_output_path),
            "--batch-consumption",
            str(
                inbox_batch_consumption_output_dir
                / "provider_live_executor_response_inbox_batch_consumption.json"
            ),
            "--batch-receipt",
            str(inbox_batch_receipt_output_path),
            "--output",
            str(inbox_status_snapshot_output_path),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    inbox_status_snapshot_payload = json.loads(inbox_status_snapshot_completed.stdout)
    inbox_status_snapshot_artifact = json.loads(
        inbox_status_snapshot_output_path.read_text(encoding="utf-8")
    )
    inbox_status_snapshot_serialized = (
        inbox_status_snapshot_completed.stdout
        + inbox_status_snapshot_output_path.read_text(encoding="utf-8")
    )

    assert (
        inbox_status_snapshot_payload["artifact_kind"]
        == "scout_wearable_provider_live_executor_response_inbox_status_snapshot_result"
    )
    assert inbox_status_snapshot_payload["manifest_status_counts"]["receipt_recorded_manifest_count"] == 1
    assert inbox_status_snapshot_artifact["source_provider"] == "apple_healthkit_live"
    assert inbox_status_snapshot_artifact["manifest_statuses"][0]["manifest_status"] == "receipt_recorded"
    assert inbox_status_snapshot_artifact["transport"]["network_request_performed"] is False
    assert inbox_status_snapshot_artifact["transport"]["real_provider_api_called"] is False
    assert inbox_status_snapshot_artifact["transport"]["runtime_ingest_performed"] is False
    assert "apple.local.executor.private" not in inbox_status_snapshot_serialized
    assert "HKWorkoutType" not in inbox_status_snapshot_serialized
    assert "HKQuantityTypeIdentifierHeartRate" not in inbox_status_snapshot_serialized
    assert "healthkit-grant-ref" not in inbox_status_snapshot_serialized
    assert "apple.health.account.private" not in inbox_status_snapshot_serialized
    assert "/safety/" not in inbox_status_snapshot_serialized

    lifecycle_audit_output_path = tmp_path / "apple-executor-lifecycle-audit.json"
    lifecycle_audit_completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scout_energy_reserve",
            "provider-live-executor-lifecycle-audit",
            "--pickup-status-snapshot",
            str(pickup_status_snapshot_output_path),
            "--inbox-status-snapshot",
            str(inbox_status_snapshot_output_path),
            "--output",
            str(lifecycle_audit_output_path),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    lifecycle_audit_payload = json.loads(lifecycle_audit_completed.stdout)
    lifecycle_audit_artifact = json.loads(
        lifecycle_audit_output_path.read_text(encoding="utf-8")
    )
    lifecycle_audit_serialized = (
        lifecycle_audit_completed.stdout
        + lifecycle_audit_output_path.read_text(encoding="utf-8")
    )

    assert (
        lifecycle_audit_payload["artifact_kind"]
        == "scout_wearable_provider_live_executor_lifecycle_audit_result"
    )
    assert lifecycle_audit_payload["local_executor_lifecycle_status"] == "local_evidence_complete"
    assert lifecycle_audit_artifact["source_provider"] == "apple_healthkit_live"
    assert lifecycle_audit_artifact["lifecycle"]["pickup_local_evidence_complete"] is True
    assert lifecycle_audit_artifact["lifecycle"]["inbox_local_evidence_complete"] is True
    assert lifecycle_audit_artifact["transport"]["network_request_performed"] is False
    assert lifecycle_audit_artifact["transport"]["real_provider_api_called"] is False
    assert lifecycle_audit_artifact["transport"]["runtime_ingest_performed"] is False
    assert "apple.local.executor.private" not in lifecycle_audit_serialized
    assert "HKWorkoutType" not in lifecycle_audit_serialized
    assert "HKQuantityTypeIdentifierHeartRate" not in lifecycle_audit_serialized
    assert "healthkit-grant-ref" not in lifecycle_audit_serialized
    assert "apple.health.account.private" not in lifecycle_audit_serialized
    assert "/safety/" not in lifecycle_audit_serialized

    credential_vault_reference_output_path = tmp_path / "apple-credential-vault-reference.json"
    credential_vault_reference_completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scout_energy_reserve",
            "provider-live-credential-vault-reference",
            "--provider",
            "apple_healthkit_live",
            "--vault-ref",
            "apple.vault.private",
            "--account-ref",
            "apple.health.account.private",
            "--token-ref",
            "healthkit-grant-ref",
            "--device-ref",
            "apple.watch.private",
            "--scope",
            "workout:read",
            "--scope",
            "heart_rate:read",
            "--capability",
            "activity_summary_import",
            "--capability",
            "heart_rate_samples",
            "--explicit-consent",
            "--output",
            str(credential_vault_reference_output_path),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    credential_vault_reference_payload = json.loads(credential_vault_reference_completed.stdout)
    credential_vault_reference_artifact = json.loads(
        credential_vault_reference_output_path.read_text(encoding="utf-8")
    )
    credential_vault_reference_serialized = (
        credential_vault_reference_completed.stdout
        + credential_vault_reference_output_path.read_text(encoding="utf-8")
    )

    assert (
        credential_vault_reference_payload["artifact_kind"]
        == "scout_wearable_provider_live_credential_vault_reference_result"
    )
    assert credential_vault_reference_artifact["source_provider"] == "apple_healthkit_live"
    assert (
        credential_vault_reference_artifact["credential_vault"][
            "credential_values_loaded"
        ]
        is False
    )
    assert (
        credential_vault_reference_artifact["credential_vault"][
            "credential_values_exposed"
        ]
        is False
    )
    assert credential_vault_reference_artifact["transport"]["network_request_performed"] is False
    assert credential_vault_reference_artifact["transport"]["real_provider_api_called"] is False
    assert credential_vault_reference_artifact["transport"]["runtime_ingest_performed"] is False
    assert "apple.vault.private" not in credential_vault_reference_serialized
    assert "apple.watch.private" not in credential_vault_reference_serialized
    assert "healthkit-grant-ref" not in credential_vault_reference_serialized
    assert "apple.health.account.private" not in credential_vault_reference_serialized
    assert "/safety/" not in credential_vault_reference_serialized

    connector_reference_output_path = tmp_path / "apple-connector-reference.json"
    connector_reference_completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scout_energy_reserve",
            "provider-live-connector-reference",
            "--provider",
            "apple_healthkit_live",
            "--connector-kind",
            "apple_healthkit_local_bridge_connector",
            "--connector-ref",
            "apple.connector.private",
            "--connector-version",
            "apple-connector-0.1.0",
            "--connector-binary-ref",
            "apple.connector.binary.private",
            "--capability",
            "activity_summary_import",
            "--capability",
            "heart_rate_samples",
            "--explicit-consent",
            "--output",
            str(connector_reference_output_path),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    connector_reference_payload = json.loads(connector_reference_completed.stdout)
    connector_reference_artifact = json.loads(
        connector_reference_output_path.read_text(encoding="utf-8")
    )
    connector_reference_serialized = (
        connector_reference_completed.stdout
        + connector_reference_output_path.read_text(encoding="utf-8")
    )

    assert (
        connector_reference_payload["artifact_kind"]
        == "scout_wearable_provider_live_connector_reference_result"
    )
    assert connector_reference_artifact["source_provider"] == "apple_healthkit_live"
    assert (
        connector_reference_artifact["connector"]["connector_kind"]
        == "apple_healthkit_local_bridge_connector"
    )
    assert connector_reference_artifact["connector"]["connector_process_started"] is False
    assert (
        connector_reference_artifact["connector"]["connector_health_check_performed"]
        is False
    )
    assert connector_reference_artifact["connector"]["connector_live_request_performed"] is False
    assert connector_reference_artifact["transport"]["network_request_performed"] is False
    assert connector_reference_artifact["transport"]["real_provider_api_called"] is False
    assert connector_reference_artifact["transport"]["runtime_ingest_performed"] is False
    assert "apple.connector.private" not in connector_reference_serialized
    assert "apple.connector.binary.private" not in connector_reference_serialized
    assert "/safety/" not in connector_reference_serialized

    network_policy_reference_output_path = tmp_path / "apple-network-policy-reference.json"
    network_policy_reference_completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scout_energy_reserve",
            "provider-live-network-policy-reference",
            "--provider",
            "apple_healthkit_live",
            "--policy-ref",
            "apple.network.policy.private",
            "--endpoint-ref",
            "apple.endpoint.private",
            "--egress-profile-ref",
            "apple.egress.private",
            "--tls-profile-ref",
            "apple.tls.private",
            "--capability",
            "activity_summary_import",
            "--capability",
            "heart_rate_samples",
            "--explicit-consent",
            "--output",
            str(network_policy_reference_output_path),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    network_policy_reference_payload = json.loads(network_policy_reference_completed.stdout)
    network_policy_reference_artifact = json.loads(
        network_policy_reference_output_path.read_text(encoding="utf-8")
    )
    network_policy_reference_serialized = (
        network_policy_reference_completed.stdout
        + network_policy_reference_output_path.read_text(encoding="utf-8")
    )

    assert (
        network_policy_reference_payload["artifact_kind"]
        == "scout_wearable_provider_live_network_policy_reference_result"
    )
    assert network_policy_reference_artifact["source_provider"] == "apple_healthkit_live"
    assert network_policy_reference_artifact["network_policy"]["dns_lookup_performed"] is False
    assert network_policy_reference_artifact["network_policy"]["network_socket_opened"] is False
    assert network_policy_reference_artifact["network_policy"]["http_request_performed"] is False
    assert network_policy_reference_artifact["network_policy"]["network_request_performed"] is False
    assert network_policy_reference_artifact["network_policy"]["real_provider_api_called"] is False
    assert network_policy_reference_artifact["transport"]["network_request_performed"] is False
    assert "apple.network.policy.private" not in network_policy_reference_serialized
    assert "apple.endpoint.private" not in network_policy_reference_serialized
    assert "apple.egress.private" not in network_policy_reference_serialized
    assert "apple.tls.private" not in network_policy_reference_serialized
    assert "/safety/" not in network_policy_reference_serialized

    runtime_ingest_boundary_reference_output_path = (
        tmp_path / "apple-runtime-ingest-boundary-reference.json"
    )
    runtime_ingest_boundary_reference_completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scout_energy_reserve",
            "provider-live-runtime-ingest-boundary-reference",
            "--provider",
            "apple_healthkit_live",
            "--runtime-boundary-ref",
            "apple.phase1.runtime.boundary.private",
            "--runtime-channel-ref",
            "apple.energy.advisory.channel.private",
            "--handoff-mode",
            "advisory_energy_reference_only",
            "--artifact-kind",
            "scout_wearable_provider_live_executor_production_readiness_gate",
            "--artifact-kind",
            "scout_energy_reserve_baseline",
            "--explicit-consent",
            "--output",
            str(runtime_ingest_boundary_reference_output_path),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    runtime_ingest_boundary_reference_payload = json.loads(
        runtime_ingest_boundary_reference_completed.stdout
    )
    runtime_ingest_boundary_reference_artifact = json.loads(
        runtime_ingest_boundary_reference_output_path.read_text(encoding="utf-8")
    )
    runtime_ingest_boundary_reference_serialized = (
        runtime_ingest_boundary_reference_completed.stdout
        + runtime_ingest_boundary_reference_output_path.read_text(encoding="utf-8")
    )

    assert (
        runtime_ingest_boundary_reference_payload["artifact_kind"]
        == "scout_wearable_provider_live_runtime_ingest_boundary_reference_result"
    )
    assert runtime_ingest_boundary_reference_artifact["source_provider"] == "apple_healthkit_live"
    assert (
        runtime_ingest_boundary_reference_artifact["runtime_ingest_boundary"][
            "runtime_ingest_authorized"
        ]
        is False
    )
    assert (
        runtime_ingest_boundary_reference_artifact["runtime_ingest_boundary"][
            "phase1_runtime_safety_truth"
        ]
        is False
    )
    assert runtime_ingest_boundary_reference_artifact["transport"]["runtime_ingest_performed"] is False
    assert runtime_ingest_boundary_reference_artifact["transport"]["safety_api_called"] is False
    assert "apple.phase1.runtime.boundary.private" not in runtime_ingest_boundary_reference_serialized
    assert "apple.energy.advisory.channel.private" not in runtime_ingest_boundary_reference_serialized
    assert "/safety/" not in runtime_ingest_boundary_reference_serialized

    phase1_safety_boundary_reference_output_path = (
        tmp_path / "apple-phase1-safety-boundary-reference.json"
    )
    phase1_safety_boundary_reference_completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scout_energy_reserve",
            "provider-live-phase1-safety-boundary-reference",
            "--provider",
            "apple_healthkit_live",
            "--phase1-boundary-ref",
            "apple.phase1.safety.boundary.private",
            "--phase1-state-ref",
            "apple.phase1.l0-l4.state.private",
            "--advisory-channel-ref",
            "apple.energy.advisory.channel.private",
            "--artifact-kind",
            "scout_wearable_provider_live_executor_production_readiness_gate",
            "--artifact-kind",
            "scout_energy_reserve_baseline",
            "--explicit-consent",
            "--output",
            str(phase1_safety_boundary_reference_output_path),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    phase1_safety_boundary_reference_payload = json.loads(
        phase1_safety_boundary_reference_completed.stdout
    )
    phase1_safety_boundary_reference_artifact = json.loads(
        phase1_safety_boundary_reference_output_path.read_text(encoding="utf-8")
    )
    phase1_safety_boundary_reference_serialized = (
        phase1_safety_boundary_reference_completed.stdout
        + phase1_safety_boundary_reference_output_path.read_text(encoding="utf-8")
    )

    assert (
        phase1_safety_boundary_reference_payload["artifact_kind"]
        == "scout_wearable_provider_live_phase1_safety_boundary_reference_result"
    )
    assert phase1_safety_boundary_reference_artifact["source_provider"] == "apple_healthkit_live"
    assert (
        phase1_safety_boundary_reference_artifact["phase1_safety_boundary"][
            "not_safety_truth"
        ]
        is True
    )
    assert (
        phase1_safety_boundary_reference_artifact["phase1_safety_boundary"][
            "phase1_runtime_safety_truth"
        ]
        is False
    )
    assert (
        phase1_safety_boundary_reference_artifact["phase1_safety_boundary"][
            "phase1_l0_l4_state_mutated"
        ]
        is False
    )
    assert phase1_safety_boundary_reference_artifact["transport"]["safety_api_called"] is False
    assert "apple.phase1.safety.boundary.private" not in phase1_safety_boundary_reference_serialized
    assert "apple.phase1.l0-l4.state.private" not in phase1_safety_boundary_reference_serialized
    assert "apple.energy.advisory.channel.private" not in phase1_safety_boundary_reference_serialized
    assert "/safety/" not in phase1_safety_boundary_reference_serialized

    production_gate_output_path = tmp_path / "apple-executor-production-readiness-gate.json"
    production_gate_completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scout_energy_reserve",
            "provider-live-executor-production-readiness-gate",
            "--lifecycle-audit",
            str(lifecycle_audit_output_path),
            "--connector-reference",
            str(connector_reference_output_path),
            "--credential-vault-reference",
            str(credential_vault_reference_output_path),
            "--network-policy-reference",
            str(network_policy_reference_output_path),
            "--runtime-ingest-boundary-reference",
            str(runtime_ingest_boundary_reference_output_path),
            "--phase1-safety-boundary-reference",
            str(phase1_safety_boundary_reference_output_path),
            "--output",
            str(production_gate_output_path),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    production_gate_payload = json.loads(production_gate_completed.stdout)
    production_gate_artifact = json.loads(
        production_gate_output_path.read_text(encoding="utf-8")
    )
    production_gate_serialized = (
        production_gate_completed.stdout
        + production_gate_output_path.read_text(encoding="utf-8")
    )

    assert (
        production_gate_payload["artifact_kind"]
        == "scout_wearable_provider_live_executor_production_readiness_gate_result"
    )
    assert production_gate_payload["production_provider_execution_ready"] is False
    assert production_gate_artifact["source_provider"] == "apple_healthkit_live"
    assert production_gate_artifact["readiness"]["local_evidence_complete"] is True
    assert production_gate_artifact["readiness"]["live_provider_connector_reference_present"] is True
    assert production_gate_artifact["readiness"]["credential_vault_reference_present"] is True
    assert production_gate_artifact["readiness"]["network_policy_reference_present"] is True
    assert production_gate_artifact["readiness"]["runtime_ingest_boundary_reference_present"] is True
    assert production_gate_artifact["readiness"]["phase1_safety_boundary_reference_present"] is True
    assert "live_provider_connector_not_implemented" not in production_gate_payload["production_blockers"]
    assert "credential_vault_not_integrated" not in production_gate_payload["production_blockers"]
    assert "network_execution_disabled_by_local_contract" not in production_gate_payload["production_blockers"]
    assert "runtime_ingest_disabled_by_boundary" in production_gate_payload["production_blockers"]
    assert "phase1_runtime_safety_truth_mutation_forbidden" in production_gate_payload["production_blockers"]
    assert (
        production_gate_artifact["inputs"]["connector_reference"][
            "connector_process_started"
        ]
        is False
    )
    assert (
        production_gate_artifact["inputs"]["credential_vault_reference"][
            "credential_values_loaded"
        ]
        is False
    )
    assert (
        production_gate_artifact["inputs"]["network_policy_reference"][
            "network_request_performed"
        ]
        is False
    )
    assert (
        production_gate_artifact["inputs"]["runtime_ingest_boundary_reference"][
            "runtime_ingest_authorized"
        ]
        is False
    )
    assert (
        production_gate_artifact["inputs"]["phase1_safety_boundary_reference"][
            "not_safety_truth"
        ]
        is True
    )
    assert (
        production_gate_artifact["inputs"]["phase1_safety_boundary_reference"][
            "phase1_l0_l4_state_mutated"
        ]
        is False
    )
    assert production_gate_artifact["transport"]["network_request_performed"] is False
    assert production_gate_artifact["transport"]["real_provider_api_called"] is False
    assert production_gate_artifact["transport"]["runtime_ingest_performed"] is False
    assert "apple.connector.private" not in production_gate_serialized
    assert "apple.connector.binary.private" not in production_gate_serialized
    assert "apple.network.policy.private" not in production_gate_serialized
    assert "apple.endpoint.private" not in production_gate_serialized
    assert "apple.phase1.safety.boundary.private" not in production_gate_serialized
    assert "apple.phase1.l0-l4.state.private" not in production_gate_serialized
    assert "apple.phase1.runtime.boundary.private" not in production_gate_serialized
    assert "apple.energy.advisory.channel.private" not in production_gate_serialized
    assert "apple.vault.private" not in production_gate_serialized
    assert "apple.watch.private" not in production_gate_serialized
    assert "apple.local.executor.private" not in production_gate_serialized
    assert "HKWorkoutType" not in production_gate_serialized
    assert "HKQuantityTypeIdentifierHeartRate" not in production_gate_serialized
    assert "healthkit-grant-ref" not in production_gate_serialized
    assert "apple.health.account.private" not in production_gate_serialized
    assert "/safety/" not in production_gate_serialized

    response_admission_output_path = tmp_path / "apple-executor-response-admission.json"
    response_admission_completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scout_energy_reserve",
            "provider-live-executor-response-admit",
            "--executor-response-manifest",
            str(response_manifest_output_path),
            "--output",
            str(response_admission_output_path),
            "--output-dir",
            str(tmp_path / "executor-response-sanitized"),
            "--activity-id-prefix",
            "live.apple.executor.response.admitted",
            "--capability",
            "activity_summary_import",
            "--capability",
            "heart_rate_samples",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    response_admission_payload = json.loads(response_admission_completed.stdout)
    response_admission_serialized = (
        response_admission_completed.stdout + response_admission_output_path.read_text(encoding="utf-8")
    )

    assert (
        response_admission_payload["artifact_kind"]
        == "scout_wearable_provider_live_executor_response_manifest_admission_result"
    )
    assert response_admission_payload["source_provider"] == "apple_healthkit_live"
    assert Path(response_admission_payload["admission_path"]).exists()
    assert response_admission_payload["admission"]["sanitized_import_result"]["activity_count"] == 2
    assert response_admission_payload["transport"]["network_request_performed"] is False
    assert response_admission_payload["transport"]["real_provider_api_called"] is False
    assert response_admission_payload["transport"]["runtime_ingest_performed"] is False
    assert "apple.local.executor.private" not in response_admission_serialized
    assert "HKWorkoutType" not in response_admission_serialized
    assert "HKQuantityTypeIdentifierHeartRate" not in response_admission_serialized
    assert "healthkit-grant-ref" not in response_admission_serialized
    assert "apple.health.account.private" not in response_admission_serialized
    assert "/safety/" not in response_admission_serialized

    consumption_output_dir = tmp_path / "apple-executor-response-consumption"
    consumption_completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scout_energy_reserve",
            "provider-live-consume-executor-response",
            "--executor-response-manifest",
            str(response_manifest_output_path),
            "--output-dir",
            str(consumption_output_dir),
            "--activity-id-prefix",
            "live.apple.executor.response.consumed",
            "--capability",
            "activity_summary_import",
            "--capability",
            "heart_rate_samples",
            "--reference-date",
            "2026-05-27",
            "--root",
            str(tmp_path),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    consumption_payload = json.loads(consumption_completed.stdout)
    consumption = consumption_payload["executor_response_consumption"]
    consumption_serialized = (
        consumption_completed.stdout
        + (consumption_output_dir / "provider_live_executor_response_consumption.json").read_text(
            encoding="utf-8"
        )
    )

    assert consumption_payload["artifact_kind"] == "scout_wearable_provider_live_executor_response_consumption_result"
    assert Path(consumption_payload["executor_response_consumption_path"]).exists()
    assert Path(consumption_payload["baseline_path"]).exists()
    assert consumption["source_provider"] == "apple_healthkit_live"
    assert consumption["executor_response_manifest"]["sha256"] == response_manifest_artifact["sha256"]
    assert consumption["admission"]["artifact_kind"] == "scout_wearable_provider_live_transport_response_admission"
    assert consumption["materialization"]["artifact_kind"] == "scout_wearable_provider_live_transport_materialization"
    assert consumption["sync_package"]["artifact_kind"] == "scout_wearable_provider_live_transport_sync_package"
    assert consumption["energy_artifacts"]["baseline"]["activity_count"] == 2
    assert consumption["transport"]["transport_mode"] == "executor_response_consumption_only"
    assert consumption["transport"]["network_request_performed"] is False
    assert consumption["transport"]["network_sync_performed"] is False
    assert consumption["transport"]["real_provider_api_called"] is False
    assert consumption["transport"]["runtime_ingest_performed"] is False
    assert consumption["boundary"]["medical_diagnosis"] is False
    assert consumption["boundary"]["phase1_runtime_safety_truth"] is False
    assert "apple.local.executor.private" not in consumption_serialized
    assert "HKWorkoutType" not in consumption_serialized
    assert "HKQuantityTypeIdentifierHeartRate" not in consumption_serialized
    assert "healthkit-grant-ref" not in consumption_serialized
    assert "apple.health.account.private" not in consumption_serialized
    assert "/safety/" not in consumption_serialized

    replay_output_path = tmp_path / "apple-fixture-replay.json"
    replay_completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scout_energy_reserve",
            "provider-live-fixture-replay",
            "--request-plan",
            str(output_path),
            "--executor-registration",
            str(registration_output_path),
            "--response-fixture",
            str(apple_response_fixture_path),
            "--output",
            str(replay_output_path),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    replay_payload = json.loads(replay_completed.stdout)
    replay_artifact = json.loads(replay_output_path.read_text(encoding="utf-8"))
    replay_serialized = replay_completed.stdout + replay_output_path.read_text(encoding="utf-8")

    assert replay_payload["artifact_kind"] == "scout_wearable_provider_live_executor_fixture_replay_result"
    assert replay_artifact["source_provider"] == "apple_healthkit_live"
    assert replay_artifact["response_fixture"]["raw_response_embedded"] is False
    assert replay_artifact["transport"]["network_request_performed"] is False
    assert replay_artifact["transport"]["real_provider_api_called"] is False
    assert replay_artifact["transport"]["runtime_ingest_performed"] is False
    assert "apple.local.executor.private" not in replay_serialized
    assert "HKWorkoutType" not in replay_serialized
    assert "HKQuantityTypeIdentifierHeartRate" not in replay_serialized
    assert "heart_rate_samples" in replay_serialized
    assert "healthkit-grant-ref" not in replay_serialized
    assert "apple.health.account.private" not in replay_serialized
    assert "/safety/" not in replay_serialized

    replay_admission_path = tmp_path / "apple-replay-admission.json"
    replay_admission_completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scout_energy_reserve",
            "provider-live-replay-admit",
            "--fixture-replay",
            str(replay_output_path),
            "--output",
            str(replay_admission_path),
            "--output-dir",
            str(tmp_path / "replay-sanitized"),
            "--activity-id-prefix",
            "live.apple.replay.admitted",
            "--capability",
            "activity_summary_import",
            "--capability",
            "heart_rate_samples",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    replay_admission_payload = json.loads(replay_admission_completed.stdout)
    replay_admission_artifact = json.loads(replay_admission_path.read_text(encoding="utf-8"))
    replay_admission_serialized = (
        replay_admission_completed.stdout + replay_admission_path.read_text(encoding="utf-8")
    )

    assert replay_admission_payload["artifact_kind"] == "scout_wearable_provider_live_executor_replay_admission_result"
    assert replay_admission_payload["admission_path"] == str(replay_admission_path)
    assert replay_admission_artifact["source_provider"] == "apple_healthkit_live"
    assert replay_admission_artifact["transport"]["network_request_performed"] is False
    assert replay_admission_artifact["transport"]["real_provider_api_called"] is False
    assert replay_admission_artifact["transport"]["runtime_ingest_performed"] is False
    assert "apple.local.executor.private" not in replay_admission_serialized
    assert "HKWorkoutType" not in replay_admission_serialized
    assert "HKQuantityTypeIdentifierHeartRate" not in replay_admission_serialized
    assert "healthkit-grant-ref" not in replay_admission_serialized
    assert "apple.health.account.private" not in replay_admission_serialized
    assert "/safety/" not in replay_admission_serialized


def test_provider_live_transport_response_admission_sanitizes_garmin_fixture_from_request_plan(tmp_path):
    preflight_result = write_provider_live_transport_preflight(
        provider="garmin_health_api_live",
        output_path=tmp_path / "preflight.json",
        explicit_consent=True,
        account_ref="garmin.account.private",
        device_ref="garmin.watch.private",
        auth_token_ref="secret-token-value",
        scopes=["activity:read", "heart_rate:read", "body_energy:read"],
        requested_capabilities=["activity_summary_import", "heart_rate_samples", "provider_body_energy_source_values"],
    )
    request_plan_result = write_provider_live_transport_request_plan(
        preflight_path=Path(preflight_result["preflight_path"]),
        output_path=tmp_path / "request-plan.json",
        window_start_date="2026-05-20",
        window_end_date="2026-05-27",
        requested_capabilities=["activity_summary_import", "provider_body_energy_source_values"],
    )
    response_fixture_path = _write_garmin_health_api_response_fixture(tmp_path / "garmin-response.json")

    result = write_provider_live_transport_response_admission(
        request_plan_path=Path(request_plan_result["request_plan_path"]),
        response_fixture_path=response_fixture_path,
        output_dir=tmp_path / "sanitized",
        activity_id_prefix="live.garmin.admitted",
        admitted_capabilities=["activity_summary_import", "provider_body_energy_source_values"],
        admission_output_path=tmp_path / "admission.json",
    )
    serialized = json.dumps(result)

    assert result["artifact_kind"] == "scout_wearable_provider_live_transport_response_admission_result"
    assert result["admission"]["artifact_kind"] == "scout_wearable_provider_live_transport_response_admission"
    assert result["admission"]["source_provider"] == "garmin_health_api_live"
    assert result["admission"]["response_fixture"]["provider_fixture"] == "garmin_health_api"
    assert result["admission"]["admitted_capabilities"] == [
        "activity_summary_import",
        "provider_body_energy_source_values",
    ]
    assert result["admission"]["sanitized_import_result"]["activity_count"] == 2
    assert all(Path(path).exists() for path in result["sanitized_import_paths"])
    assert result["admission"]["transport"]["network_request_performed"] is False
    assert result["admission"]["transport"]["real_provider_api_called"] is False
    assert result["admission"]["transport"]["runtime_ingest_performed"] is False
    assert result["admission"]["mutation"]["raw_payload_committed"] is False
    assert result["admission"]["privacy"]["raw_health_payload_shared"] is False
    assert result["admission"]["boundary"]["medical_diagnosis"] is False
    assert result["admission"]["boundary"]["phase1_runtime_safety_truth"] is False
    assert "secret-token-value" not in serialized
    assert "garmin.account.private" not in serialized
    assert "garmin.watch.private" not in serialized
    assert "heartRateSamples" not in serialized
    assert "geoPolylineDTO" not in serialized
    assert "startTimeGMT" not in serialized
    assert "/safety/" not in serialized

    materialized = write_provider_live_transport_materialization(
        admission_path=Path(result["admission_path"]),
        output_dir=tmp_path / "normalized",
        materialization_output_path=tmp_path / "materialization.json",
        root=tmp_path,
    )
    materialized_payload = json.dumps(materialized)

    assert materialized["artifact_kind"] == "scout_wearable_provider_live_transport_materialization_result"
    assert materialized["materialization"]["artifact_kind"] == "scout_wearable_provider_live_transport_materialization"
    assert materialized["materialization"]["source_provider"] == "garmin_health_api_live"
    assert materialized["normalization"]["activity_count"] == 2
    assert materialized["materialization"]["transport"]["runtime_ingest_performed"] is False
    assert materialized["materialization"]["mutation"]["phase1_runtime_mutated"] is False
    for normalized_path in materialized["normalized_paths"]:
        report = validate_wearable_activity_summary_contract(Path(normalized_path), root=tmp_path)
        assert report.valid is True
    assert "heartRateSamples" not in materialized_payload
    assert "geoPolylineDTO" not in materialized_payload
    assert "/safety/" not in materialized_payload

    sync_package = write_provider_live_transport_sync_package(
        materialization_path=Path(materialized["materialization_path"]),
        package_output_path=tmp_path / "sync-package.json",
        root=tmp_path,
    )
    sync_payload = json.dumps(sync_package)

    assert sync_package["artifact_kind"] == "scout_wearable_provider_live_transport_sync_package_result"
    assert sync_package["sync_package"]["artifact_kind"] == "scout_wearable_provider_live_transport_sync_package"
    assert sync_package["sync_package"]["source_provider"] == "garmin_health_api_live"
    assert sync_package["sync_package"]["normalized_summary_count"] == 2
    assert all(item["valid"] is True for item in sync_package["sync_package"]["normalized_summaries"])
    assert sync_package["sync_package"]["transport"]["transport_mode"] == "local_sync_package_only"
    assert sync_package["sync_package"]["transport"]["network_sync_performed"] is False
    assert sync_package["sync_package"]["transport"]["remote_upload_allowed"] is False
    assert sync_package["sync_package"]["transport"]["runtime_ingest_performed"] is False
    assert sync_package["sync_package"]["mutation"]["phase1_runtime_mutated"] is False
    assert "heartRateSamples" not in sync_payload
    assert "geoPolylineDTO" not in sync_payload
    assert "/safety/" not in sync_payload


def test_provider_live_transport_response_admission_rejects_unplanned_capability(tmp_path):
    preflight_result = write_provider_live_transport_preflight(
        provider="apple_healthkit_live",
        output_path=tmp_path / "preflight.json",
        explicit_consent=True,
        account_ref="apple.health.account.private",
        auth_token_ref="healthkit-grant-ref",
        scopes=["HKWorkoutType"],
        requested_capabilities=["activity_summary_import"],
    )
    request_plan_result = write_provider_live_transport_request_plan(
        preflight_path=Path(preflight_result["preflight_path"]),
        output_path=tmp_path / "request-plan.json",
        window_start_date="2026-05-20",
        window_end_date="2026-05-27",
        requested_capabilities=["activity_summary_import"],
    )

    try:
        write_provider_live_transport_response_admission(
            request_plan_path=Path(request_plan_result["request_plan_path"]),
            response_fixture_path=_write_apple_healthkit_response_fixture(tmp_path / "apple-response.json"),
            output_dir=tmp_path / "sanitized",
            activity_id_prefix="live.apple.admitted",
            admitted_capabilities=["heart_rate_samples"],
        )
    except ValueError as exc:
        assert "not present in provider live request plan" in str(exc)
    else:
        raise AssertionError("response admission should reject unplanned capabilities")


def test_provider_live_transport_response_admission_cli_writes_descriptor_and_sanitized_imports(tmp_path):
    preflight_result = write_provider_live_transport_preflight(
        provider="apple_healthkit_live",
        output_path=tmp_path / "preflight.json",
        explicit_consent=True,
        account_ref="apple.health.account.private",
        device_ref="apple.watch.private",
        auth_token_ref="healthkit-grant-ref",
        scopes=["HKWorkoutType", "HKQuantityTypeIdentifierHeartRate"],
        requested_capabilities=["activity_summary_import", "heart_rate_samples"],
    )
    request_plan_result = write_provider_live_transport_request_plan(
        preflight_path=Path(preflight_result["preflight_path"]),
        output_path=tmp_path / "request-plan.json",
        window_start_date="2026-05-20",
        window_end_date="2026-05-27",
        requested_capabilities=["activity_summary_import", "heart_rate_samples"],
    )
    response_fixture_path = _write_apple_healthkit_response_fixture(tmp_path / "apple-response.json")
    admission_path = tmp_path / "admission.json"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scout_energy_reserve",
            "provider-live-response-admit",
            "--request-plan",
            request_plan_result["request_plan_path"],
            "--response-fixture",
            str(response_fixture_path),
            "--output",
            str(admission_path),
            "--output-dir",
            str(tmp_path / "sanitized"),
            "--activity-id-prefix",
            "live.apple.admitted",
            "--capability",
            "activity_summary_import",
            "--capability",
            "heart_rate_samples",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(completed.stdout)
    admission = json.loads(admission_path.read_text(encoding="utf-8"))
    serialized = completed.stdout + admission_path.read_text(encoding="utf-8")

    assert payload["artifact_kind"] == "scout_wearable_provider_live_transport_response_admission_result"
    assert payload["admission_path"] == str(admission_path)
    assert admission["source_provider"] == "apple_healthkit_live"
    assert admission["response_fixture"]["provider_fixture"] == "apple_healthkit_api"
    assert admission["sanitized_import_result"]["activity_count"] == 2
    assert admission["transport"]["network_request_performed"] is False
    assert admission["transport"]["real_provider_api_called"] is False
    assert admission["transport"]["runtime_ingest_performed"] is False
    assert "HKWorkoutType" not in serialized
    assert "HKQuantityTypeIdentifierHeartRate" not in serialized
    assert "healthkit-grant-ref" not in serialized
    assert "apple.health.account.private" not in serialized
    assert "/safety/" not in serialized


def test_provider_live_transport_materialization_cli_normalizes_admitted_imports(tmp_path):
    preflight_result = write_provider_live_transport_preflight(
        provider="apple_healthkit_live",
        output_path=tmp_path / "preflight.json",
        explicit_consent=True,
        account_ref="apple.health.account.private",
        device_ref="apple.watch.private",
        auth_token_ref="healthkit-grant-ref",
        scopes=["HKWorkoutType", "HKQuantityTypeIdentifierHeartRate"],
        requested_capabilities=["activity_summary_import", "heart_rate_samples"],
    )
    request_plan_result = write_provider_live_transport_request_plan(
        preflight_path=Path(preflight_result["preflight_path"]),
        output_path=tmp_path / "request-plan.json",
        window_start_date="2026-05-20",
        window_end_date="2026-05-27",
        requested_capabilities=["activity_summary_import", "heart_rate_samples"],
    )
    admission_result = write_provider_live_transport_response_admission(
        request_plan_path=Path(request_plan_result["request_plan_path"]),
        response_fixture_path=_write_apple_healthkit_response_fixture(tmp_path / "apple-response.json"),
        output_dir=tmp_path / "sanitized",
        activity_id_prefix="live.apple.admitted",
        admitted_capabilities=["activity_summary_import", "heart_rate_samples"],
        admission_output_path=tmp_path / "admission.json",
    )
    materialization_path = tmp_path / "materialization.json"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scout_energy_reserve",
            "provider-live-materialize",
            "--admission",
            admission_result["admission_path"],
            "--output",
            str(materialization_path),
            "--output-dir",
            str(tmp_path / "normalized"),
            "--root",
            str(tmp_path),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(completed.stdout)
    materialization = json.loads(materialization_path.read_text(encoding="utf-8"))
    serialized = completed.stdout + materialization_path.read_text(encoding="utf-8")

    assert payload["artifact_kind"] == "scout_wearable_provider_live_transport_materialization_result"
    assert materialization["artifact_kind"] == "scout_wearable_provider_live_transport_materialization"
    assert materialization["source_provider"] == "apple_healthkit_live"
    assert materialization["normalization"]["activity_count"] == 2
    assert all(Path(path).exists() for path in payload["normalized_paths"])
    assert materialization["transport"]["network_request_performed"] is False
    assert materialization["transport"]["real_provider_api_called"] is False
    assert materialization["transport"]["runtime_ingest_performed"] is False
    assert materialization["mutation"]["safety_api_called"] is False
    assert "HKWorkoutType" not in serialized
    assert "HKQuantityTypeIdentifierHeartRate" not in serialized
    assert "healthkit-grant-ref" not in serialized
    assert "apple.health.account.private" not in serialized


def test_provider_live_transport_sync_package_cli_wraps_materialized_summaries(tmp_path):
    preflight_result = write_provider_live_transport_preflight(
        provider="apple_healthkit_live",
        output_path=tmp_path / "preflight.json",
        explicit_consent=True,
        account_ref="apple.health.account.private",
        device_ref="apple.watch.private",
        auth_token_ref="healthkit-grant-ref",
        scopes=["HKWorkoutType", "HKQuantityTypeIdentifierHeartRate"],
        requested_capabilities=["activity_summary_import", "heart_rate_samples"],
    )
    request_plan_result = write_provider_live_transport_request_plan(
        preflight_path=Path(preflight_result["preflight_path"]),
        output_path=tmp_path / "request-plan.json",
        window_start_date="2026-05-20",
        window_end_date="2026-05-27",
        requested_capabilities=["activity_summary_import", "heart_rate_samples"],
    )
    admission_result = write_provider_live_transport_response_admission(
        request_plan_path=Path(request_plan_result["request_plan_path"]),
        response_fixture_path=_write_apple_healthkit_response_fixture(tmp_path / "apple-response.json"),
        output_dir=tmp_path / "sanitized",
        activity_id_prefix="live.apple.admitted",
        admitted_capabilities=["activity_summary_import", "heart_rate_samples"],
        admission_output_path=tmp_path / "admission.json",
    )
    materialization_result = write_provider_live_transport_materialization(
        admission_path=Path(admission_result["admission_path"]),
        output_dir=tmp_path / "normalized",
        materialization_output_path=tmp_path / "materialization.json",
        root=tmp_path,
    )
    package_path = tmp_path / "sync-package.json"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scout_energy_reserve",
            "provider-live-sync-package",
            "--materialization",
            materialization_result["materialization_path"],
            "--output",
            str(package_path),
            "--root",
            str(tmp_path),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(completed.stdout)
    package = json.loads(package_path.read_text(encoding="utf-8"))
    serialized = completed.stdout + package_path.read_text(encoding="utf-8")

    assert payload["artifact_kind"] == "scout_wearable_provider_live_transport_sync_package_result"
    assert payload["sync_package_path"] == str(package_path)
    assert package["artifact_kind"] == "scout_wearable_provider_live_transport_sync_package"
    assert package["source_provider"] == "apple_healthkit_live"
    assert package["normalized_summary_count"] == 2
    assert package["transport"]["network_request_performed"] is False
    assert package["transport"]["network_sync_performed"] is False
    assert package["transport"]["remote_upload_performed"] is False
    assert package["transport"]["runtime_ingest_performed"] is False
    assert package["boundary"]["medical_diagnosis"] is False
    assert package["boundary"]["phase1_runtime_safety_truth"] is False
    assert all(item["valid"] is True for item in package["normalized_summaries"])
    assert "HKWorkoutType" not in serialized
    assert "HKQuantityTypeIdentifierHeartRate" not in serialized
    assert "healthkit-grant-ref" not in serialized
    assert "apple.health.account.private" not in serialized
    assert "/safety/" not in serialized

    energy_output_dir = tmp_path / "energy"
    energy_completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scout_energy_reserve",
            "provider-live-build-energy",
            "--sync-package",
            str(package_path),
            "--output-dir",
            str(energy_output_dir),
            "--reference-date",
            "2026-05-27",
            "--root",
            str(tmp_path),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    energy_payload = json.loads(energy_completed.stdout)
    energy_serialized = energy_completed.stdout

    assert energy_payload["artifact_kind"] == "scout_energy_reserve_provider_sync_package_build_result"
    assert energy_payload["source_provider"] == "apple_healthkit_live"
    assert energy_payload["sync_package"]["sha256"] == package["sha256"]
    assert Path(energy_payload["baseline_path"]).exists()
    assert Path(energy_payload["explanation_path"]).exists()
    assert Path(energy_payload["companion_capsule_path"]).exists()
    assert energy_payload["energy_artifacts"]["baseline"]["activity_count"] == 2
    assert energy_payload["transport"]["network_sync_performed"] is False
    assert energy_payload["transport"]["remote_upload_performed"] is False
    assert energy_payload["transport"]["runtime_ingest_performed"] is False
    assert energy_payload["boundary"]["medical_diagnosis"] is False
    assert energy_payload["boundary"]["phase1_runtime_safety_truth"] is False
    assert "HKWorkoutType" not in energy_serialized
    assert "HKQuantityTypeIdentifierHeartRate" not in energy_serialized
    assert "healthkit-grant-ref" not in energy_serialized
    assert "apple.health.account.private" not in energy_serialized
    assert "/safety/" not in energy_serialized


def test_provider_live_executor_rehearsal_cli_runs_local_pipeline_without_network(tmp_path):
    preflight_result = write_provider_live_transport_preflight(
        provider="garmin_health_api_live",
        output_path=tmp_path / "preflight.json",
        explicit_consent=True,
        account_ref="garmin.account.private",
        device_ref="garmin.watch.private",
        auth_token_ref="secret-token-value",
        scopes=["activity:read", "heart_rate:read", "body_energy:read"],
        requested_capabilities=["activity_summary_import", "provider_body_energy_source_values"],
    )
    request_plan_result = write_provider_live_transport_request_plan(
        preflight_path=Path(preflight_result["preflight_path"]),
        output_path=tmp_path / "request-plan.json",
        window_start_date="2026-05-20",
        window_end_date="2026-05-27",
        requested_capabilities=["activity_summary_import", "provider_body_energy_source_values"],
    )
    registration_result = write_provider_live_executor_registration(
        preflight_path=Path(preflight_result["preflight_path"]),
        output_path=tmp_path / "executor-registration.json",
        executor_kind="garmin_health_api_client",
        executor_ref="local.garmin.executor.private",
        supported_capabilities=["activity_summary_import", "provider_body_energy_source_values"],
    )
    response_fixture_path = _write_garmin_health_api_response_fixture(tmp_path / "garmin-response.json")
    output_dir = tmp_path / "executor-rehearsal"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scout_energy_reserve",
            "provider-live-rehearse-executor",
            "--request-plan",
            request_plan_result["request_plan_path"],
            "--executor-registration",
            registration_result["executor_registration_path"],
            "--response-fixture",
            str(response_fixture_path),
            "--output-dir",
            str(output_dir),
            "--activity-id-prefix",
            "live.garmin.rehearsed",
            "--capability",
            "activity_summary_import",
            "--capability",
            "provider_body_energy_source_values",
            "--reference-date",
            "2026-05-27",
            "--root",
            str(tmp_path),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(completed.stdout)
    rehearsal = payload["executor_rehearsal"]
    serialized = completed.stdout + (output_dir / "provider_live_executor_rehearsal.json").read_text(encoding="utf-8")

    assert payload["artifact_kind"] == "scout_wearable_provider_live_executor_rehearsal_result"
    assert Path(payload["executor_rehearsal_path"]).exists()
    assert rehearsal["artifact_kind"] == "scout_wearable_provider_live_executor_rehearsal"
    assert rehearsal["source_provider"] == "garmin_health_api_live"
    assert rehearsal["readiness"]["ready_for_live_execution"] is False
    assert rehearsal["readiness"]["execution_blockers"] == [
        "network_execution_disabled_by_local_contract"
    ]
    assert rehearsal["admission"]["artifact_kind"] == "scout_wearable_provider_live_transport_response_admission"
    assert rehearsal["materialization"]["artifact_kind"] == "scout_wearable_provider_live_transport_materialization"
    assert rehearsal["sync_package"]["artifact_kind"] == "scout_wearable_provider_live_transport_sync_package"
    assert rehearsal["energy_artifacts"]["baseline"]["activity_count"] == 2
    assert Path(payload["executor_handoff_path"]).exists()
    assert Path(payload["executor_response_manifest_path"]).exists()
    assert rehearsal["fixture_replay"]["handoff_package_sha256"]
    assert (
        rehearsal["executor_response_manifest"]["artifact_kind"]
        == "scout_wearable_provider_live_executor_response_manifest"
    )
    assert rehearsal["executor_response_manifest"]["raw_response_embedded"] is False
    assert Path(payload["admission_path"]).exists()
    assert Path(payload["materialization_path"]).exists()
    assert Path(payload["sync_package_path"]).exists()
    assert Path(payload["baseline_path"]).exists()
    assert rehearsal["transport"]["transport_mode"] == "executor_rehearsal_only"
    assert rehearsal["transport"]["network_request_performed"] is False
    assert rehearsal["transport"]["network_sync_performed"] is False
    assert rehearsal["transport"]["real_provider_api_called"] is False
    assert rehearsal["transport"]["runtime_ingest_performed"] is False
    assert rehearsal["mutation"]["phase1_runtime_mutated"] is False
    assert rehearsal["boundary"]["medical_diagnosis"] is False
    assert rehearsal["boundary"]["phase1_runtime_safety_truth"] is False
    assert "local.garmin.executor.private" not in serialized
    assert "secret-token-value" not in serialized
    assert "garmin.account.private" not in serialized
    assert "garmin.watch.private" not in serialized
    assert "heartRateSamples" not in serialized
    assert "geoPolylineDTO" not in serialized
    assert "/safety/" not in serialized


def test_provider_live_transport_preflight_normalizes_apple_scopes_without_network():
    artifact = build_provider_live_transport_preflight(
        provider="apple_healthkit_live",
        explicit_consent=True,
        account_ref="apple.health.account.private",
        device_ref="apple.watch.private",
        auth_token_ref="healthkit-grant-ref",
        scopes=["HKWorkoutType", "HKQuantityTypeIdentifierHeartRate", "HKQuantityTypeIdentifierUnknown"],
        requested_capabilities=["activity_summary_import", "heart_rate_samples", "live_frame_stream"],
    )
    serialized = json.dumps(artifact)

    assert artifact["source_provider"] == "apple_healthkit_live"
    assert artifact["source_path"] == "provider-live-preflight://apple_healthkit_live"
    assert len(artifact["sha256"]) == 64
    assert artifact["authorization"]["normalized_scopes"] == ["heart_rate:read", "workout:read"]
    assert artifact["authorization"]["unsupported_scope_count"] == 1
    assert artifact["capability_review"]["allowed_capabilities"] == [
        "activity_summary_import",
        "heart_rate_samples",
        "live_frame_stream",
    ]
    assert artifact["transport"]["transport_mode"] == "preflight_only"
    assert artifact["transport"]["network_request_performed"] is False
    assert artifact["transport"]["real_provider_api_called"] is False
    assert artifact["transport"]["runtime_ingest_performed"] is False
    assert artifact["privacy"]["exact_timestamps_shared"] is False
    assert artifact["boundary"]["safety_api_calls_allowed"] is False
    assert "HKWorkoutType" not in serialized
    assert "HKQuantityTypeIdentifierHeartRate" not in serialized
    assert "HKQuantityTypeIdentifierUnknown" not in serialized
    assert "healthkit-grant-ref" not in serialized


def test_provider_live_transport_preflight_rejects_live_effect_flags():
    try:
        build_provider_live_transport_preflight(
            provider="garmin_health_api_live",
            explicit_consent=True,
            account_ref="garmin.account.private",
            auth_token_ref="secret-token-value",
            scopes=["activity:read"],
            requested_capabilities=["activity_summary_import"],
            network_request_performed=bool(1),
        )
    except ValueError as exc:
        assert "preflight cannot perform network requests" in str(exc)
    else:
        raise AssertionError("preflight must reject network effects")


def test_provider_live_transport_preflight_cli_writes_artifact_without_provider_call(tmp_path):
    output_path = tmp_path / "garmin-live-preflight.json"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scout_energy_reserve",
            "provider-live-preflight",
            "--provider",
            "garmin_health_api_live",
            "--output",
            str(output_path),
            "--account-ref",
            "garmin.account.private",
            "--device-ref",
            "garmin.watch.private",
            "--auth-token-ref",
            "secret-token-value",
            "--scope",
            "activity:read",
            "--scope",
            "heart_rate:read",
            "--capability",
            "activity_summary_import",
            "--capability",
            "heart_rate_samples",
            "--explicit-consent",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(completed.stdout)
    artifact = json.loads(output_path.read_text(encoding="utf-8"))
    serialized = completed.stdout + output_path.read_text(encoding="utf-8")

    assert payload["artifact_kind"] == "scout_wearable_provider_live_transport_preflight_result"
    assert payload["preflight_path"] == str(output_path)
    assert artifact["artifact_kind"] == "scout_wearable_provider_live_transport_preflight"
    assert artifact["source_provider"] == "garmin_health_api_live"
    assert artifact["authorization"]["normalized_scopes"] == ["activity:read", "heart_rate:read"]
    assert artifact["capability_review"]["allowed_capabilities"] == [
        "activity_summary_import",
        "heart_rate_samples",
    ]
    assert artifact["transport"]["network_request_performed"] is False
    assert artifact["transport"]["real_provider_api_called"] is False
    assert artifact["transport"]["runtime_ingest_performed"] is False
    assert artifact["mutation"]["raw_payload_committed"] is False
    assert artifact["privacy"]["raw_health_payload_shared"] is False
    assert artifact["boundary"]["phase1_runtime_safety_truth"] is False
    assert "secret-token-value" not in serialized
    assert "garmin.account.private" not in serialized
    assert "garmin.watch.private" not in serialized


def _write_garmin_health_api_response_fixture(path: Path) -> Path:
    payload = {
        "activities": [
            {
                "activityId": 987654321,
                "startTimeGMT": "2026-05-26T00:00:00Z",
                "duration": 3600,
                "movingDuration": 3400,
                "distance": 4100,
                "elevationGain": 180,
                "elevationLoss": 175,
                "heartRateSamples": [
                    {"timeOffsetSeconds": 0, "heartRate": 105},
                    {"timeOffsetSeconds": 1800, "heartRate": 128},
                    {"timeOffsetSeconds": 3400, "heartRate": 119},
                ],
                "bodyBattery": {"start": 72, "end": 51},
                "stress": {"avg": 42},
                "geoPolylineDTO": {"polyline": "private-route-one"},
            },
            {
                "activityId": 987654322,
                "startTimeGMT": "2026-05-27T00:00:00Z",
                "duration": 5400,
                "movingDuration": 5000,
                "distance": 5600,
                "elevationGain": 320,
                "elevationLoss": 315,
                "heartRateSamples": [
                    {"timeOffsetSeconds": 0, "heartRate": 98},
                    {"timeOffsetSeconds": 1400, "heartRate": 126},
                    {"timeOffsetSeconds": 3200, "heartRate": 142},
                    {"timeOffsetSeconds": 5000, "heartRate": 119},
                ],
                "bodyBattery": {"start": 68, "end": 38},
                "stress": {"avg": 59},
                "geoPolylineDTO": {"polyline": "private-route-two"},
            },
        ]
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _write_apple_healthkit_response_fixture(path: Path) -> Path:
    payload = {
        "workouts": [
            {
                "uuid": "apple-workout-001",
                "workoutActivityType": "HKWorkoutActivityTypeHiking",
                "startDate": "2026-05-26T07:00:00+08:00",
                "endDate": "2026-05-26T07:45:00+08:00",
                "duration_s": 2700,
                "distance_m": 3100,
                "heart_rate_samples": [
                    {"startDate": "2026-05-26T07:10:00+08:00", "bpm": 118},
                    {"startDate": "2026-05-26T07:40:00+08:00", "bpm": 132},
                ],
            },
            {
                "uuid": "apple-workout-002",
                "workoutActivityType": "HKWorkoutActivityTypeHiking",
                "startDate": "2026-05-27T07:00:00+08:00",
                "endDate": "2026-05-27T08:00:00+08:00",
                "duration_s": 3600,
                "distance_m": 4200,
                "heart_rate_samples": [
                    {"startDate": "2026-05-27T07:05:00+08:00", "bpm": 110},
                    {"startDate": "2026-05-27T07:35:00+08:00", "bpm": 136},
                ],
                "quantity_type": "HKQuantityTypeIdentifierHeartRate",
            },
        ]
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path
