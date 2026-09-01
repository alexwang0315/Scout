from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from scout_runtime_safety_live_evidence_bridge import (
    write_cwa_live_evidence_bundles,
    write_mqtt_live_evidence_bundles,
    write_phase1_writer_live_evidence_bundle,
    write_pi_live_evidence_bundles,
)
from scout_runtime_safety_cwa_credential_rotation import (
    build_cwa_credential_rotation_receipt,
)
from scout_runtime_safety_live_qualification import (
    CwaLiveQualificationConfig,
    run_cwa_live_qualification,
)
from scout_runtime_safety_production_qualification import (
    evaluate_production_safety_qualification_bundle,
    verify_production_safety_qualification_source_integrity,
)
from scout_runtime_safety_mqtt_live_qualification import (
    MqttLiveQualificationConfig,
    MqttTransportObservation,
    build_mqtt_consumer_receipt,
    run_mqtt_live_qualification,
)
from scout_hardware_readiness_live_probe import build_probe_result
from scout_runtime_safety_pi_live_qualification import (
    PiGnssObservation,
    PiRuntimeObservation,
    run_pi_live_qualification,
)
from scout_runtime_safety_phase1_writer_live_qualification import (
    Phase1WriterRuntimeObservation,
    run_phase1_writer_live_qualification,
)


def _reviewed_after(path) -> datetime:
    observed_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return observed_at + timedelta(seconds=1)


def _report(*, execution_host_ref: str):
    config = CwaLiveQualificationConfig(
        source_path="prod://qualification/cwa/live-run-001",
        run_id="cwa-live-run-001",
        execution_host_ref=execution_host_ref,
        route_scope_ref="runtime://route/chilai-nanhua/day1",
        route_id="runtime.route.chilai-nanhua",
        segment_id="seg.001",
        location_name="南投縣",
        credential_ref="secret://scout/cwa/opendata-api-token",
        operator_identity_ref="operator://identity/scout-owner",
        operator_role="scout_owner",
        allow_live_provider_call=True,
    )
    return run_cwa_live_qualification(
        config,
        env={"SCOUT_CWA_API_KEY": "test-secret-value"},
        fetcher=lambda _dataset_id, **_kwargs: {
            "success": "true",
            "records": {"location": [{"locationName": "南投縣"}]},
        },
        now=datetime(2026, 8, 31, 3, 0, tzinfo=timezone.utc),
    )


def test_cwa_live_evidence_bridge_preserves_credential_rotation_gap(tmp_path) -> None:
    report = _report(execution_host_ref="pi://scout/runtime")
    test_evidence = tmp_path / "cwa-live.junit.xml"
    test_evidence.write_text("<testsuite tests='6' failures='0' />\n", encoding="utf-8")
    reviewed_at = datetime.now(timezone.utc) + timedelta(minutes=1)

    paths_by_area = write_cwa_live_evidence_bundles(
        report,
        test_evidence_path=test_evidence,
        output_root=tmp_path / "areas",
        qualification_root_ref="prod://qualification/scout-safety-production-20260831",
        reviewer_ref="operator://qualification/scout-owner/cwa-live-review",
        reviewed_at=reviewed_at,
    )

    assert set(paths_by_area) == {
        "live_provider_api",
        "connector_health_endpoint",
        "credential_access_path",
    }
    decisions = {}
    for area, paths in paths_by_area.items():
        bundle = json.loads(paths.bundle_path.read_text(encoding="utf-8"))
        package = json.loads(paths.source_package_path.read_text(encoding="utf-8"))
        integrity = verify_production_safety_qualification_source_integrity(
            bundle,
            package,
            root_path=tmp_path / "areas",
            source_path=(
                "prod://qualification/scout-safety-production-20260831/areas/"
                f"{area}/source-integrity"
            ),
        )
        decisions[area] = evaluate_production_safety_qualification_bundle(
            bundle,
            source_integrity_report=integrity,
        )

    assert decisions["live_provider_api"].status == "qualification_receipt_accepted"
    assert decisions["connector_health_endpoint"].status == (
        "qualification_receipt_accepted"
    )
    assert decisions["credential_access_path"].status == (
        "blocked_rejected_required_claims"
    )


def test_cwa_live_evidence_bridge_rejects_non_pi_execution_report(tmp_path) -> None:
    report = _report(execution_host_ref="prod://runtime/macos-qualification-host")
    test_evidence = tmp_path / "cwa-live.junit.xml"
    test_evidence.write_text("<testsuite tests='6' failures='0' />\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Pi execution evidence"):
        write_cwa_live_evidence_bundles(
            report,
            test_evidence_path=test_evidence,
            output_root=tmp_path / "areas",
            qualification_root_ref=(
                "prod://qualification/scout-safety-production-20260831"
            ),
            reviewer_ref="operator://qualification/scout-owner/cwa-live-review",
            reviewed_at=report.observed_at + timedelta(minutes=5),
        )


def test_cwa_live_evidence_bridge_accepts_verified_rotation_receipt(tmp_path) -> None:
    report = _report(execution_host_ref="pi://scout/runtime")
    test_evidence = tmp_path / "cwa-live.junit.xml"
    test_evidence.write_text("<testsuite tests='6' failures='0' />\n", encoding="utf-8")
    receipt = build_cwa_credential_rotation_receipt(
        source_path=(
            "prod://qualification/scout-safety-production-20260831/"
            "cwa-credential-rotation"
        ),
        observed_at=_reviewed_after(test_evidence),
        credential_ref=report.credential_ref,
        provider_management_ref="https://opendata.cwa.gov.tw/user/authkey",
        operator_identity_ref="operator://identity/scout-owner",
        live_report=report,
        provider_rotation_observed=True,
        previous_credential_invalidated=True,
        credential_scope_verified=True,
        mac_secret_refs_updated=True,
        pi_secret_ref_updated=True,
        pi_runtime_credential_refs_configured=True,
        secret_file_permissions_verified=True,
    )
    reviewed_at = receipt.observed_at + timedelta(seconds=1)

    paths_by_area = write_cwa_live_evidence_bundles(
        report,
        credential_rotation_receipt=receipt,
        test_evidence_path=test_evidence,
        output_root=tmp_path / "areas",
        qualification_root_ref="prod://qualification/scout-safety-production-20260831",
        reviewer_ref="operator://qualification/scout-owner/cwa-live-review",
        reviewed_at=reviewed_at,
    )
    paths = paths_by_area["credential_access_path"]
    bundle = json.loads(paths.bundle_path.read_text(encoding="utf-8"))
    package = json.loads(paths.source_package_path.read_text(encoding="utf-8"))
    integrity = verify_production_safety_qualification_source_integrity(
        bundle,
        package,
        root_path=tmp_path / "areas",
        source_path=(
            "prod://qualification/scout-safety-production-20260831/areas/"
            "credential_access_path/source-integrity"
        ),
    )
    decision = evaluate_production_safety_qualification_bundle(
        bundle,
        source_integrity_report=integrity,
    )

    assert decision.status == "qualification_receipt_accepted"
    rotation_claim = json.loads(
        (paths.claim_artifact_paths[-1]).read_text(encoding="utf-8")
    )
    assert receipt.source_path in rotation_claim["source_artifact_refs"]
    assert rotation_claim["credential_material_present"] is False


def test_cwa_live_evidence_bridge_rejects_mismatched_rotation_receipt(
    tmp_path,
) -> None:
    report = _report(execution_host_ref="pi://scout/runtime")
    other_report = report.model_copy(update={"sha256": "f" * 64})
    receipt = build_cwa_credential_rotation_receipt(
        source_path="prod://qualification/run-001/cwa-credential-rotation",
        observed_at=report.observed_at + timedelta(minutes=1),
        credential_ref=report.credential_ref,
        provider_management_ref="https://opendata.cwa.gov.tw/user/authkey",
        operator_identity_ref="operator://identity/scout-owner",
        live_report=other_report,
        provider_rotation_observed=True,
        previous_credential_invalidated=True,
        credential_scope_verified=True,
        mac_secret_refs_updated=True,
        pi_secret_ref_updated=True,
        pi_runtime_credential_refs_configured=True,
        secret_file_permissions_verified=True,
    )
    test_evidence = tmp_path / "cwa-live.junit.xml"
    test_evidence.write_text("<testsuite tests='6' failures='0' />\n", encoding="utf-8")

    with pytest.raises(ValueError, match="live report lineage"):
        write_cwa_live_evidence_bundles(
            report,
            credential_rotation_receipt=receipt,
            test_evidence_path=test_evidence,
            output_root=tmp_path / "areas",
            qualification_root_ref=(
                "prod://qualification/scout-safety-production-20260831"
            ),
            reviewer_ref="operator://qualification/scout-owner/cwa-live-review",
            reviewed_at=receipt.observed_at + timedelta(seconds=1),
        )


def _mqtt_report(*, broker_allows_anonymous: bool):
    config = MqttLiveQualificationConfig(
        source_path="prod://qualification/mqtt/live-run-001",
        run_id="mqtt-live-run-001",
        execution_host_ref="pi://scout/runtime",
        broker_ref="transport://mqtt/scout/chirpstack-mosquitto",
        topic="scout/qualification/safety-emergency/live-run-001",
        consumer_receipt_topic=(
            "scout/qualification/safety-emergency/live-run-001/receipt"
        ),
        operator_identity_ref="operator://identity/scout-owner",
        allow_publish=True,
    )

    def transport(config_model, payload: str, payload_sha256: str):
        receipt = build_mqtt_consumer_receipt(
            config_model,
            payload=payload,
            payload_sha256=payload_sha256,
            received_at=datetime(2026, 8, 31, 4, 1, tzinfo=timezone.utc),
        )
        return MqttTransportObservation(
            publish_exit_code=0,
            broker_ack_observed=True,
            consumer_message_received=True,
            consumer_receipt_received=True,
            consumer_receipt_payload=json.dumps(receipt, sort_keys=True),
            network_connection_attempted=True,
            external_send_performed=True,
            broker_allows_anonymous=broker_allows_anonymous,
            credential_ref_applied=True,
        )

    return run_mqtt_live_qualification(
        config,
        transport=transport,
        now=datetime(2026, 8, 31, 4, 0, tzinfo=timezone.utc),
    )


def test_mqtt_live_evidence_bridge_qualifies_transport_and_delivery(tmp_path) -> None:
    report = _mqtt_report(broker_allows_anonymous=False)
    test_evidence = tmp_path / "mqtt-live.junit.xml"
    test_evidence.write_text("<testsuite tests='5' failures='0' />\n", encoding="utf-8")

    paths_by_area = write_mqtt_live_evidence_bundles(
        report,
        test_evidence_path=test_evidence,
        output_root=tmp_path / "areas",
        qualification_root_ref="prod://qualification/scout-safety-production-20260831",
        reviewer_ref="operator://qualification/scout-owner/mqtt-live-review",
        reviewed_at=_reviewed_after(test_evidence),
    )

    assert set(paths_by_area) == {"transport_client", "outbound_delivery"}
    for area, paths in paths_by_area.items():
        bundle = json.loads(paths.bundle_path.read_text(encoding="utf-8"))
        package = json.loads(paths.source_package_path.read_text(encoding="utf-8"))
        integrity = verify_production_safety_qualification_source_integrity(
            bundle,
            package,
            root_path=tmp_path / "areas",
            source_path=(
                "prod://qualification/scout-safety-production-20260831/areas/"
                f"{area}/source-integrity"
            ),
        )
        decision = evaluate_production_safety_qualification_bundle(
            bundle,
            source_integrity_report=integrity,
        )
        assert decision.status == "qualification_receipt_accepted"


def test_mqtt_live_evidence_bridge_keeps_anonymous_transport_gap_open(tmp_path) -> None:
    report = _mqtt_report(broker_allows_anonymous=True)
    test_evidence = tmp_path / "mqtt-live.junit.xml"
    test_evidence.write_text("<testsuite tests='5' failures='0' />\n", encoding="utf-8")

    paths_by_area = write_mqtt_live_evidence_bundles(
        report,
        test_evidence_path=test_evidence,
        output_root=tmp_path / "areas",
        qualification_root_ref="prod://qualification/scout-safety-production-20260831",
        reviewer_ref="operator://qualification/scout-owner/mqtt-live-review",
        reviewed_at=_reviewed_after(test_evidence),
    )

    transport_paths = paths_by_area["transport_client"]
    delivery_paths = paths_by_area["outbound_delivery"]
    transport_integrity = verify_production_safety_qualification_source_integrity(
        json.loads(transport_paths.bundle_path.read_text(encoding="utf-8")),
        json.loads(transport_paths.source_package_path.read_text(encoding="utf-8")),
        root_path=tmp_path / "areas",
        source_path=(
            "prod://qualification/scout-safety-production-20260831/areas/"
            "transport_client/source-integrity"
        ),
    )
    delivery_integrity = verify_production_safety_qualification_source_integrity(
        json.loads(delivery_paths.bundle_path.read_text(encoding="utf-8")),
        json.loads(delivery_paths.source_package_path.read_text(encoding="utf-8")),
        root_path=tmp_path / "areas",
        source_path=(
            "prod://qualification/scout-safety-production-20260831/areas/"
            "outbound_delivery/source-integrity"
        ),
    )
    transport = evaluate_production_safety_qualification_bundle(
        json.loads(transport_paths.bundle_path.read_text(encoding="utf-8")),
        source_integrity_report=transport_integrity,
    )
    delivery = evaluate_production_safety_qualification_bundle(
        json.loads(delivery_paths.bundle_path.read_text(encoding="utf-8")),
        source_integrity_report=delivery_integrity,
    )

    assert transport.status == "blocked_rejected_required_claims"
    assert delivery.status == "qualification_receipt_accepted"


def _pi_report(*, control_mismatch: bool, freshness_resident: bool):
    probe = build_probe_result(
        "scout",
        """
__SCOUT_PROBE_SECTION__ host
host=scout
kernel=Linux 6.12 aarch64 GNU/Linux
date=2026-08-31T12:00:00+08:00
__SCOUT_PROBE_SECTION__ uart
/dev/ttyAMA0
""",
    )
    runtime = PiRuntimeObservation(
        observed_at="2026-08-31T04:00:00Z",
        host="scout",
        architecture="aarch64",
        machine_identity_sha256="a" * 64,
        admin_container_running=True,
        admin_container_health="healthy",
        mqtt_container_running=True,
        gnss_observer_process_running=True,
        freshness_attestor_process_running=False,
        freshness_attestor_reported_resident_process_observed=freshness_resident,
        freshness_attestor_status=(
            "freshness_attestation_complete" if freshness_resident else None
        ),
        freshness_attestor_heartbeat_count=2 if freshness_resident else 0,
        freshness_attestor_current_source_count=1 if freshness_resident else 0,
        freshness_attestor_stale_source_rejected=freshness_resident,
        freshness_attestor_status_sha256=("b" * 64 if freshness_resident else None),
        gnss_observer_visual_control_configured=control_mismatch,
        gnss_observer_reported_hardware_control_allowed=False,
        gnss_observer_reported_hardware_control_performed=False,
        gnss_observer_updated_at="2026-08-31T03:59:58Z",
        gnss_selected_observed_at="2026-06-16T02:18:30Z",
    )
    gnss = PiGnssObservation(
        status="blocked_no_nmea_stream",
        observed_at="2026-08-31T04:00:05Z",
        device_ref="device://scout/gnss",
        sentence_count=0,
        valid_fix_count=0,
        checksum_valid_count=0,
        checksum_invalid_count=0,
        read_only_hardware_access=True,
    )
    return run_pi_live_qualification(
        host_ref="pi://scout/runtime",
        source_path="prod://qualification/run-001/pi-live",
        probe=probe,
        runtime=runtime,
        gnss=gnss,
        now=datetime(2026, 8, 31, 4, 1, tzinfo=timezone.utc),
    )


def test_pi_live_evidence_bridge_qualifies_all_three_areas_when_ready(tmp_path) -> None:
    report = _pi_report(control_mismatch=False, freshness_resident=True)
    test_evidence = tmp_path / "pi-live.junit.xml"
    test_evidence.write_text("<testsuite tests='3' failures='0' />\n", encoding="utf-8")

    paths_by_area = write_pi_live_evidence_bundles(
        report,
        test_evidence_path=test_evidence,
        output_root=tmp_path / "areas",
        qualification_root_ref="prod://qualification/scout-safety-production-20260831",
        reviewer_ref="operator://qualification/scout-owner/pi-live-review",
        reviewed_at=_reviewed_after(test_evidence),
    )

    assert set(paths_by_area) == {
        "resident_freshness_attestor",
        "field_device_validator",
        "pi_hardware",
    }
    for area, paths in paths_by_area.items():
        bundle = json.loads(paths.bundle_path.read_text(encoding="utf-8"))
        package = json.loads(paths.source_package_path.read_text(encoding="utf-8"))
        integrity = verify_production_safety_qualification_source_integrity(
            bundle,
            package,
            root_path=tmp_path / "areas",
            source_path=(
                "prod://qualification/scout-safety-production-20260831/areas/"
                f"{area}/source-integrity"
            ),
        )
        decision = evaluate_production_safety_qualification_bundle(
            bundle,
            source_integrity_report=integrity,
        )
        assert decision.status == "qualification_receipt_accepted"


def test_pi_live_evidence_bridge_preserves_real_runtime_blockers(tmp_path) -> None:
    report = _pi_report(control_mismatch=True, freshness_resident=False)
    test_evidence = tmp_path / "pi-live.junit.xml"
    test_evidence.write_text("<testsuite tests='3' failures='0' />\n", encoding="utf-8")

    paths_by_area = write_pi_live_evidence_bundles(
        report,
        test_evidence_path=test_evidence,
        output_root=tmp_path / "areas",
        qualification_root_ref="prod://qualification/scout-safety-production-20260831",
        reviewer_ref="operator://qualification/scout-owner/pi-live-review",
        reviewed_at=_reviewed_after(test_evidence),
    )

    decisions = {}
    for area, paths in paths_by_area.items():
        bundle = json.loads(paths.bundle_path.read_text(encoding="utf-8"))
        package = json.loads(paths.source_package_path.read_text(encoding="utf-8"))
        integrity = verify_production_safety_qualification_source_integrity(
            bundle,
            package,
            root_path=tmp_path / "areas",
            source_path=(
                "prod://qualification/scout-safety-production-20260831/areas/"
                f"{area}/source-integrity"
            ),
        )
        decisions[area] = evaluate_production_safety_qualification_bundle(
            bundle,
            source_integrity_report=integrity,
        )

    assert decisions["field_device_validator"].status == (
        "qualification_receipt_accepted"
    )
    assert decisions["pi_hardware"].status == "blocked_rejected_required_claims"
    assert decisions["resident_freshness_attestor"].status == (
        "blocked_rejected_required_claims"
    )


@pytest.mark.parametrize(
    ("runtime_ready", "expected_status"),
    [
        (True, "qualification_receipt_accepted"),
        (False, "blocked_rejected_required_claims"),
    ],
)
def test_phase1_writer_evidence_bridge_preserves_deployment_state(
    tmp_path,
    runtime_ready: bool,
    expected_status: str,
) -> None:
    reviewed_sha256 = "d" * 64
    observation = Phase1WriterRuntimeObservation(
        observed_at="2026-08-31T05:00:00Z",
        host="scout",
        architecture="aarch64",
        admin_container_running=True,
        admin_container_health="healthy",
        container_image_identity_sha256="a" * 64,
        module_present=True,
        deployed_module_sha256=reviewed_sha256 if runtime_ready else "e" * 64,
        writer_invocation_request_symbol_present=runtime_ready,
        writer_invocation_function_present=runtime_ready,
        deployment_manifest_symbol_present=runtime_ready,
        deployment_readiness_function_present=runtime_ready,
    )
    report = run_phase1_writer_live_qualification(
        host_ref="pi://scout/runtime",
        source_path="prod://qualification/run-001/phase1-writer",
        observation=observation,
        reviewed_module_sha256=reviewed_sha256,
    )
    test_evidence = tmp_path / "phase1-writer.junit.xml"
    test_evidence.write_text(
        "<testsuite tests='15' failures='0' />\n",
        encoding="utf-8",
    )
    paths = write_phase1_writer_live_evidence_bundle(
        report,
        test_evidence_path=test_evidence,
        output_root=tmp_path / "areas",
        qualification_root_ref="prod://qualification/scout-safety-production-20260831",
        reviewer_ref="operator://qualification/scout-owner/phase1-writer-review",
        reviewed_at=_reviewed_after(test_evidence),
    )
    bundle = json.loads(paths.bundle_path.read_text(encoding="utf-8"))
    package = json.loads(paths.source_package_path.read_text(encoding="utf-8"))
    integrity = verify_production_safety_qualification_source_integrity(
        bundle,
        package,
        root_path=tmp_path / "areas",
        source_path=(
            "prod://qualification/scout-safety-production-20260831/areas/"
            "phase1_writer_deployment/source-integrity"
        ),
    )
    decision = evaluate_production_safety_qualification_bundle(
        bundle,
        source_integrity_report=integrity,
    )

    assert decision.status == expected_status
