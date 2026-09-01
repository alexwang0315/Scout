from __future__ import annotations

import argparse
import json
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

from scout_energy_models import aggregate_sha256, sha256_file
from scout_runtime_safety_cwa_credential_rotation import (
    CwaCredentialRotationReceipt,
    load_cwa_credential_rotation_receipt,
)
from scout_runtime_safety_live_qualification import (
    CwaLiveQualificationReport,
    load_cwa_live_qualification_report,
)
from scout_runtime_safety_mqtt_live_qualification import (
    MqttLiveQualificationReport,
    load_mqtt_live_qualification_report,
)
from scout_runtime_safety_phase1_writer_live_qualification import (
    Phase1WriterLiveQualificationReport,
    load_phase1_writer_live_qualification_report,
)
from scout_runtime_safety_pi_live_qualification import (
    PiLiveQualificationReport,
    load_pi_live_qualification_report,
)
from scout_runtime_safety_production_qualification import (
    PRODUCTION_SAFETY_QUALIFICATION_REQUIRED_CLAIMS,
)
from scout_runtime_safety_qualification_evidence import (
    ProductionQualificationAreaEvidencePaths,
    ProductionQualificationAreaEvidenceRequest,
    ProductionQualificationClaimSource,
    write_production_qualification_area_evidence,
)


_CWA_QUALIFICATION_AREAS = (
    "live_provider_api",
    "connector_health_endpoint",
    "credential_access_path",
)
_TEST_BACKED_CLAIMS = {
    "fail_closed_behavior_verified",
    "rollback_or_fallback_verified",
    "connector_degraded_fail_closed",
}
_MQTT_QUALIFICATION_AREAS = (
    "transport_client",
    "outbound_delivery",
)
_MQTT_TEST_BACKED_CLAIMS = {
    "fail_closed_behavior_verified",
    "rollback_or_fallback_verified",
    "gateway_ack_rejected_as_insufficient",
}
_PI_QUALIFICATION_AREAS = (
    "resident_freshness_attestor",
    "field_device_validator",
    "pi_hardware",
)
_PI_TEST_BACKED_CLAIMS = {
    "fail_closed_behavior_verified",
    "rollback_or_fallback_verified",
    "stale_source_rejected",
    "disputed_validation_rejected",
    "pi_hardware_fail_closed_verified",
}
_PHASE1_WRITER_TEST_BACKED_CLAIMS = {
    "fail_closed_behavior_verified",
    "rollback_or_fallback_verified",
    "guarded_writer_invocation_verified",
    "production_write_boundary_reviewed",
}


def write_cwa_live_evidence_bundles(
    report: CwaLiveQualificationReport,
    *,
    credential_rotation_receipt: CwaCredentialRotationReceipt | None = None,
    test_evidence_path: str | Path,
    output_root: str | Path,
    qualification_root_ref: str,
    reviewer_ref: str,
    reviewed_at: datetime,
) -> dict[str, ProductionQualificationAreaEvidencePaths]:
    if report.status != "cwa_live_chain_verified":
        raise ValueError("CWA live report must be verified before evidence bridging")
    if not report.execution_host_ref.startswith("pi://"):
        raise ValueError("CWA production qualification requires Pi execution evidence")
    if reviewed_at.tzinfo is None or reviewed_at.utcoffset() is None:
        raise ValueError("reviewed_at must be timezone-aware")
    if credential_rotation_receipt is not None:
        _validate_cwa_rotation_receipt(
            report,
            credential_rotation_receipt,
            reviewed_at=reviewed_at,
        )

    test_path = Path(test_evidence_path)
    test_sha256 = sha256_file(test_path)
    tests_passed = _junit_passed(test_path)
    test_observed_at = datetime.fromtimestamp(
        test_path.stat().st_mtime,
        tz=timezone.utc,
    )
    observed_times = [report.observed_at, test_observed_at]
    if credential_rotation_receipt is not None:
        observed_times.append(credential_rotation_receipt.observed_at)
    evidence_observed_at = max(observed_times)
    if evidence_observed_at > reviewed_at:
        raise ValueError("reviewed_at cannot predate report or test evidence")

    root_ref = qualification_root_ref.rstrip("/")
    test_ref = f"{root_ref}/tests/cwa-live-qualification"
    reviewer_sha256 = aggregate_sha256(
        [
            {
                "reviewer_ref": reviewer_ref,
                "reviewed_at": reviewed_at.isoformat(),
                "report_sha256": report.sha256,
                "test_sha256": test_sha256,
                "credential_rotation_receipt_sha256": (
                    credential_rotation_receipt.sha256
                    if credential_rotation_receipt is not None
                    else None
                ),
            }
        ]
    )
    output: dict[str, ProductionQualificationAreaEvidencePaths] = {}
    for area in _CWA_QUALIFICATION_AREAS:
        area_ref = f"{root_ref}/areas/{area}"
        boundary_ref = f"attestation://qualification/{area}/cwa-live-boundary"
        boundary_sha256 = aggregate_sha256(
            [
                {
                    "area": area,
                    "report_sha256": report.sha256,
                    "test_sha256": test_sha256,
                    "credential_material_embedded": False,
                    "raw_payload_embedded": False,
                }
            ]
        )
        claims = [
            _claim_source(
                report,
                area=area,
                claim_id=claim_id,
                test_ref=test_ref,
                test_sha256=test_sha256,
                tests_passed=tests_passed,
                observed_at=evidence_observed_at,
                credential_rotation_receipt=credential_rotation_receipt,
            )
            for claim_id in PRODUCTION_SAFETY_QUALIFICATION_REQUIRED_CLAIMS[area]
        ]
        notes = [
            "Pi CWA live execution and focused fail-closed tests are hash-bound.",
            "No credential value or raw CWA payload is included.",
        ]
        if area == "credential_access_path":
            if (
                credential_rotation_receipt is not None
                and credential_rotation_receipt.ready_for_credential_qualification
            ):
                notes.append(
                    "Credential scope and rotation are bound to a current sanitized provider-operation receipt."
                )
            else:
                notes.append(
                    "Credential scope and rotation remain rejected until a current reviewed provider-operation receipt is supplied."
                )
        output[area] = write_production_qualification_area_evidence(
            ProductionQualificationAreaEvidenceRequest(
                area=area,
                source_provider="scout_runtime_safety_live_evidence_bridge",
                source_path=area_ref,
                reference_time=reviewed_at,
                qualification_ref=report.source_path,
                qualification_sha256=report.sha256,
                reviewed_effect_boundary_ref=boundary_ref,
                reviewed_effect_boundary_sha256=boundary_sha256,
                operator_review_ref=reviewer_ref,
                operator_review_sha256=reviewer_sha256,
                reviewer_observed_at=reviewed_at,
                max_age_seconds=3600,
                claims=claims,
                notes=notes,
            ),
            output_root,
        )
    return output


def write_mqtt_live_evidence_bundles(
    report: MqttLiveQualificationReport,
    *,
    test_evidence_path: str | Path,
    output_root: str | Path,
    qualification_root_ref: str,
    reviewer_ref: str,
    reviewed_at: datetime,
) -> dict[str, ProductionQualificationAreaEvidencePaths]:
    if not report.outbound_delivery_evidence_ready:
        raise ValueError("MQTT report must contain verified consumer delivery")
    if not report.execution_host_ref.startswith("pi://"):
        raise ValueError("MQTT production qualification requires Pi execution evidence")
    if reviewed_at.tzinfo is None or reviewed_at.utcoffset() is None:
        raise ValueError("reviewed_at must be timezone-aware")

    test_path = Path(test_evidence_path)
    test_sha256 = sha256_file(test_path)
    tests_passed = _junit_passed(test_path)
    test_observed_at = datetime.fromtimestamp(
        test_path.stat().st_mtime,
        tz=timezone.utc,
    )
    evidence_observed_at = max(report.observed_at, test_observed_at)
    if evidence_observed_at > reviewed_at:
        raise ValueError("reviewed_at cannot predate report or test evidence")

    root_ref = qualification_root_ref.rstrip("/")
    test_ref = f"{root_ref}/tests/mqtt-live-qualification"
    reviewer_sha256 = aggregate_sha256(
        [
            {
                "reviewer_ref": reviewer_ref,
                "reviewed_at": reviewed_at.isoformat(),
                "report_sha256": report.sha256,
                "test_sha256": test_sha256,
            }
        ]
    )
    output: dict[str, ProductionQualificationAreaEvidencePaths] = {}
    for area in _MQTT_QUALIFICATION_AREAS:
        area_ref = f"{root_ref}/areas/{area}"
        boundary_ref = f"attestation://qualification/{area}/mqtt-live-boundary"
        boundary_sha256 = aggregate_sha256(
            [
                {
                    "area": area,
                    "report_sha256": report.sha256,
                    "test_sha256": test_sha256,
                    "qualification_topic": report.topic,
                    "retain": report.retain,
                    "credential_material_embedded": False,
                    "raw_transport_payload_embedded": False,
                }
            ]
        )
        claims = [
            _mqtt_claim_source(
                report,
                area=area,
                claim_id=claim_id,
                test_ref=test_ref,
                test_sha256=test_sha256,
                tests_passed=tests_passed,
                observed_at=evidence_observed_at,
            )
            for claim_id in PRODUCTION_SAFETY_QUALIFICATION_REQUIRED_CLAIMS[area]
        ]
        notes = [
            "Pi MQTT publish and consumer-side receipt are hash-bound.",
            "Broker PUBACK is not accepted as delivery confirmation.",
            "No credential value or raw MQTT payload is included.",
        ]
        if report.broker_allows_anonymous:
            notes.append(
                "Transport credential qualification remains rejected because the broker allows anonymous connections."
            )
        output[area] = write_production_qualification_area_evidence(
            ProductionQualificationAreaEvidenceRequest(
                area=area,
                source_provider="scout_runtime_safety_live_evidence_bridge",
                source_path=area_ref,
                reference_time=reviewed_at,
                qualification_ref=report.source_path,
                qualification_sha256=report.sha256,
                reviewed_effect_boundary_ref=boundary_ref,
                reviewed_effect_boundary_sha256=boundary_sha256,
                operator_review_ref=reviewer_ref,
                operator_review_sha256=reviewer_sha256,
                reviewer_observed_at=reviewed_at,
                max_age_seconds=3600,
                claims=claims,
                notes=notes,
            ),
            output_root,
        )
    return output


def write_pi_live_evidence_bundles(
    report: PiLiveQualificationReport,
    *,
    test_evidence_path: str | Path,
    output_root: str | Path,
    qualification_root_ref: str,
    reviewer_ref: str,
    reviewed_at: datetime,
) -> dict[str, ProductionQualificationAreaEvidencePaths]:
    if not report.host_ref.startswith("pi://") or not report.pi_runtime_observed:
        raise ValueError("Pi live report must contain a running Pi runtime")
    if reviewed_at.tzinfo is None or reviewed_at.utcoffset() is None:
        raise ValueError("reviewed_at must be timezone-aware")

    test_path = Path(test_evidence_path)
    test_sha256 = sha256_file(test_path)
    tests_passed = _junit_passed(test_path)
    test_observed_at = datetime.fromtimestamp(
        test_path.stat().st_mtime,
        tz=timezone.utc,
    )
    evidence_observed_at = max(report.observed_at, test_observed_at)
    if evidence_observed_at > reviewed_at:
        raise ValueError("reviewed_at cannot predate report or test evidence")

    root_ref = qualification_root_ref.rstrip("/")
    test_ref = f"{root_ref}/tests/pi-live-qualification"
    reviewer_sha256 = aggregate_sha256(
        [
            {
                "reviewer_ref": reviewer_ref,
                "reviewed_at": reviewed_at.isoformat(),
                "report_sha256": report.sha256,
                "test_sha256": test_sha256,
            }
        ]
    )
    output: dict[str, ProductionQualificationAreaEvidencePaths] = {}
    for area in _PI_QUALIFICATION_AREAS:
        area_ref = f"{root_ref}/areas/{area}"
        boundary_ref = f"attestation://qualification/{area}/pi-live-boundary"
        boundary_sha256 = aggregate_sha256(
            [
                {
                    "area": area,
                    "report_sha256": report.sha256,
                    "test_sha256": test_sha256,
                    "runtime_safety_truth_mutated": False,
                    "raw_location_payload_embedded": False,
                    "qualification_hardware_control_performed": False,
                }
            ]
        )
        claims = [
            _pi_claim_source(
                report,
                area=area,
                claim_id=claim_id,
                test_ref=test_ref,
                test_sha256=test_sha256,
                tests_passed=tests_passed,
                observed_at=evidence_observed_at,
            )
            for claim_id in PRODUCTION_SAFETY_QUALIFICATION_REQUIRED_CLAIMS[area]
        ]
        notes = [
            "Pi runtime identity, read-only hardware metadata, and redacted GNSS evidence are hash-bound.",
            "Coordinates, raw NMEA, motion, credentials, and raw device identifiers are excluded.",
            "No service restart, hardware drive, Safety API call, or runtime safety mutation was performed by qualification.",
        ]
        if report.observer_hardware_control_boundary_mismatch:
            notes.append(
                "Pi hardware qualification remains rejected because the resident observer control flags do not match its OLED/LED launch configuration."
            )
        if report.resident_freshness_attestor_observed:
            notes.append(
                "Resident freshness evidence came from a bounded, hashed Pi attestor run and does not prove continuous-service deployment."
            )
        else:
            notes.append(
                "Resident freshness qualification remains rejected because no dedicated freshness attestor process was observed."
            )
        output[area] = write_production_qualification_area_evidence(
            ProductionQualificationAreaEvidenceRequest(
                area=area,
                source_provider="scout_runtime_safety_live_evidence_bridge",
                source_path=area_ref,
                reference_time=reviewed_at,
                qualification_ref=report.source_path,
                qualification_sha256=report.sha256,
                reviewed_effect_boundary_ref=boundary_ref,
                reviewed_effect_boundary_sha256=boundary_sha256,
                operator_review_ref=reviewer_ref,
                operator_review_sha256=reviewer_sha256,
                reviewer_observed_at=reviewed_at,
                max_age_seconds=3600,
                claims=claims,
                notes=notes,
            ),
            output_root,
        )
    return output


def write_phase1_writer_live_evidence_bundle(
    report: Phase1WriterLiveQualificationReport,
    *,
    test_evidence_path: str | Path,
    output_root: str | Path,
    qualification_root_ref: str,
    reviewer_ref: str,
    reviewed_at: datetime,
) -> ProductionQualificationAreaEvidencePaths:
    if not report.host_ref.startswith("pi://") or not report.pi_runtime_observed:
        raise ValueError("Phase 1 writer report must contain a running Pi runtime")
    if reviewed_at.tzinfo is None or reviewed_at.utcoffset() is None:
        raise ValueError("reviewed_at must be timezone-aware")

    test_path = Path(test_evidence_path)
    test_sha256 = sha256_file(test_path)
    tests_passed = _junit_passed(test_path)
    test_observed_at = datetime.fromtimestamp(
        test_path.stat().st_mtime,
        tz=timezone.utc,
    )
    evidence_observed_at = max(report.observed_at, test_observed_at)
    if evidence_observed_at > reviewed_at:
        raise ValueError("reviewed_at cannot predate report or test evidence")

    area = "phase1_writer_deployment"
    root_ref = qualification_root_ref.rstrip("/")
    area_ref = f"{root_ref}/areas/{area}"
    test_ref = f"{root_ref}/tests/phase1-writer-qualification"
    boundary_ref = f"attestation://qualification/{area}/pi-runtime-boundary"
    boundary_sha256 = aggregate_sha256(
        [
            {
                "area": area,
                "report_sha256": report.sha256,
                "test_sha256": test_sha256,
                "production_runtime_write_performed": False,
                "production_runtime_safety_truth_mutated": False,
                "phase1_l0_l4_state_mutated": False,
            }
        ]
    )
    reviewer_sha256 = aggregate_sha256(
        [
            {
                "reviewer_ref": reviewer_ref,
                "reviewed_at": reviewed_at.isoformat(),
                "report_sha256": report.sha256,
                "test_sha256": test_sha256,
            }
        ]
    )
    claims = [
        _phase1_writer_claim_source(
            report,
            claim_id=claim_id,
            test_ref=test_ref,
            test_sha256=test_sha256,
            tests_passed=tests_passed,
            observed_at=evidence_observed_at,
        )
        for claim_id in PRODUCTION_SAFETY_QUALIFICATION_REQUIRED_CLAIMS[area]
    ]
    notes = [
        "Pi container identity and deployed Phase 1 module surface are hash-bound.",
        "Focused local guard and mutation tests are supporting evidence only and do not prove deployment.",
        "Qualification does not invoke the writer, deploy code, restart services, mutate runtime state, call the Safety API, send transport, or control hardware.",
    ]
    if not report.phase1_writer_runtime_deployed:
        notes.append(
            "Phase 1 writer deployment remains rejected until the reviewed module and guard surfaces are present in the Pi runtime."
        )
    return write_production_qualification_area_evidence(
        ProductionQualificationAreaEvidenceRequest(
            area=area,
            source_provider="scout_runtime_safety_live_evidence_bridge",
            source_path=area_ref,
            reference_time=reviewed_at,
            qualification_ref=report.source_path,
            qualification_sha256=report.sha256,
            reviewed_effect_boundary_ref=boundary_ref,
            reviewed_effect_boundary_sha256=boundary_sha256,
            operator_review_ref=reviewer_ref,
            operator_review_sha256=reviewer_sha256,
            reviewer_observed_at=reviewed_at,
            max_age_seconds=3600,
            claims=claims,
            notes=notes,
        ),
        output_root,
    )


def _claim_source(
    report: CwaLiveQualificationReport,
    *,
    area: str,
    claim_id: str,
    test_ref: str,
    test_sha256: str,
    tests_passed: bool,
    observed_at: datetime,
    credential_rotation_receipt: CwaCredentialRotationReceipt | None,
) -> ProductionQualificationClaimSource:
    uses_test_evidence = claim_id in _TEST_BACKED_CLAIMS
    verified = _claim_verified(
        report,
        area=area,
        claim_id=claim_id,
        tests_passed=tests_passed,
        credential_rotation_receipt=credential_rotation_receipt,
    )
    refs = [report.source_path]
    hashes = [report.sha256]
    if uses_test_evidence:
        refs.append(test_ref)
        hashes.append(test_sha256)
    if (
        claim_id == "credential_scope_and_rotation_verified"
        and credential_rotation_receipt is not None
    ):
        refs.append(credential_rotation_receipt.source_path)
        hashes.append(credential_rotation_receipt.sha256)
    return ProductionQualificationClaimSource(
        claim_id=claim_id,
        source_artifact_refs=refs,
        source_artifact_sha256s=hashes,
        observed_at=observed_at,
        verified=verified,
        summary=_claim_summary(area, claim_id, verified),
    )


def _claim_verified(
    report: CwaLiveQualificationReport,
    *,
    area: str,
    claim_id: str,
    tests_passed: bool,
    credential_rotation_receipt: CwaCredentialRotationReceipt | None,
) -> bool:
    if claim_id in _TEST_BACKED_CLAIMS:
        return tests_passed
    if claim_id == "production_environment_verified":
        return report.execution_host_ref.startswith("pi://")
    if claim_id == "credential_ref_resolved_without_value":
        return report.credential_ref_resolved_without_value
    if claim_id == "credential_scope_and_rotation_verified":
        return bool(
            credential_rotation_receipt is not None
            and credential_rotation_receipt.ready_for_credential_qualification
        )
    if area == "credential_access_path":
        return report.credential_ref_resolved_without_value
    if area == "connector_health_endpoint":
        return report.connector_health_evidence_ready
    return report.live_provider_api_evidence_ready


def _validate_cwa_rotation_receipt(
    report: CwaLiveQualificationReport,
    receipt: CwaCredentialRotationReceipt,
    *,
    reviewed_at: datetime,
) -> None:
    if (
        receipt.post_rotation_live_report_ref != report.source_path
        or receipt.post_rotation_live_report_sha256 != report.sha256
        or receipt.post_rotation_live_report_observed_at != report.observed_at
    ):
        raise ValueError("credential rotation receipt live report lineage mismatch")
    if receipt.credential_ref != report.credential_ref:
        raise ValueError("credential rotation receipt credential ref mismatch")
    if receipt.execution_host_ref != report.execution_host_ref:
        raise ValueError("credential rotation receipt execution host mismatch")
    if receipt.observed_at > reviewed_at:
        raise ValueError("reviewed_at cannot predate credential rotation receipt")


def _claim_summary(area: str, claim_id: str, verified: bool) -> str:
    result = "verified" if verified else "not verified"
    return f"{area} claim {claim_id} was {result} by sanitized Pi CWA evidence."


def _mqtt_claim_source(
    report: MqttLiveQualificationReport,
    *,
    area: str,
    claim_id: str,
    test_ref: str,
    test_sha256: str,
    tests_passed: bool,
    observed_at: datetime,
) -> ProductionQualificationClaimSource:
    uses_test_evidence = claim_id in _MQTT_TEST_BACKED_CLAIMS
    verified = _mqtt_claim_verified(
        report,
        claim_id=claim_id,
        tests_passed=tests_passed,
    )
    refs = [report.source_path]
    hashes = [report.sha256]
    if uses_test_evidence:
        refs.append(test_ref)
        hashes.append(test_sha256)
    result = "verified" if verified else "not verified"
    return ProductionQualificationClaimSource(
        claim_id=claim_id,
        source_artifact_refs=refs,
        source_artifact_sha256s=hashes,
        observed_at=observed_at,
        verified=verified,
        summary=(
            f"{area} claim {claim_id} was {result} by sanitized Pi MQTT evidence."
        ),
    )


def _mqtt_claim_verified(
    report: MqttLiveQualificationReport,
    *,
    claim_id: str,
    tests_passed: bool,
) -> bool:
    if claim_id in _MQTT_TEST_BACKED_CLAIMS:
        return tests_passed
    if claim_id == "production_environment_verified":
        return report.execution_host_ref.startswith("pi://")
    if claim_id in {
        "capability_observed",
        "transport_client_execution_observed",
        "approved_outbound_send_observed",
    }:
        return report.transport_client_execution_observed
    if claim_id == "lineage_verified":
        return bool(report.payload_sha256 and report.consumer_receipt_sha256)
    if claim_id == "transport_credential_ref_only":
        return report.transport_credential_ref_only
    if claim_id == "transport_delivery_verifier_bound":
        return report.delivery_verifier_bound
    if claim_id == "delivery_confirmation_verified":
        return report.outbound_delivery_evidence_ready
    return report.outbound_delivery_evidence_ready


def _pi_claim_source(
    report: PiLiveQualificationReport,
    *,
    area: str,
    claim_id: str,
    test_ref: str,
    test_sha256: str,
    tests_passed: bool,
    observed_at: datetime,
) -> ProductionQualificationClaimSource:
    uses_test_evidence = claim_id in _PI_TEST_BACKED_CLAIMS
    verified = _pi_claim_verified(
        report,
        area=area,
        claim_id=claim_id,
        tests_passed=tests_passed,
    )
    refs = [report.source_path]
    hashes = [report.sha256]
    if uses_test_evidence:
        refs.append(test_ref)
        hashes.append(test_sha256)
    result = "verified" if verified else "not verified"
    return ProductionQualificationClaimSource(
        claim_id=claim_id,
        source_artifact_refs=refs,
        source_artifact_sha256s=hashes,
        observed_at=observed_at,
        verified=verified,
        summary=(
            f"{area} claim {claim_id} was {result} by sanitized Pi runtime evidence."
        ),
    )


def _pi_claim_verified(
    report: PiLiveQualificationReport,
    *,
    area: str,
    claim_id: str,
    tests_passed: bool,
) -> bool:
    if claim_id == "production_environment_verified":
        return report.host_ref.startswith("pi://") and report.pi_runtime_observed
    if claim_id == "lineage_verified":
        return bool(report.runtime_observation_sha256 and report.gnss_observation_sha256)
    if claim_id == "rollback_or_fallback_verified":
        return tests_passed
    if claim_id == "fail_closed_behavior_verified":
        area_fail_closed = {
            "resident_freshness_attestor": report.stale_source_rejected,
            "field_device_validator": report.disputed_validation_rejected,
            "pi_hardware": report.pi_hardware_fail_closed_verified,
        }[area]
        return tests_passed and area_fail_closed
    claim_values = {
        "freshness_attestor_resident_observed": (
            report.resident_freshness_attestor_observed
        ),
        "freshness_window_enforced": report.freshness_window_enforced,
        "stale_source_rejected": report.stale_source_rejected and tests_passed,
        "field_device_observation_observed": (
            report.field_device_observation_observed
        ),
        "device_or_field_evidence_bound": report.device_or_field_evidence_bound,
        "disputed_validation_rejected": (
            report.disputed_validation_rejected and tests_passed
        ),
        "pi_runtime_observed": report.pi_runtime_observed,
        "pi_device_identity_verified": report.pi_device_identity_verified,
        "pi_hardware_fail_closed_verified": (
            report.pi_hardware_fail_closed_verified and tests_passed
        ),
    }
    if claim_id == "capability_observed":
        return {
            "resident_freshness_attestor": report.freshness_window_enforced,
            "field_device_validator": report.field_device_observation_observed,
            "pi_hardware": report.pi_runtime_observed,
        }[area]
    return bool(claim_values.get(claim_id, False))


def _phase1_writer_claim_source(
    report: Phase1WriterLiveQualificationReport,
    *,
    claim_id: str,
    test_ref: str,
    test_sha256: str,
    tests_passed: bool,
    observed_at: datetime,
) -> ProductionQualificationClaimSource:
    uses_test_evidence = claim_id in _PHASE1_WRITER_TEST_BACKED_CLAIMS
    verified = _phase1_writer_claim_verified(
        report,
        claim_id=claim_id,
        tests_passed=tests_passed,
    )
    refs = [report.source_path]
    hashes = [report.sha256]
    if uses_test_evidence:
        refs.append(test_ref)
        hashes.append(test_sha256)
    result = "verified" if verified else "not verified"
    return ProductionQualificationClaimSource(
        claim_id=claim_id,
        source_artifact_refs=refs,
        source_artifact_sha256s=hashes,
        observed_at=observed_at,
        verified=verified,
        summary=(
            f"phase1_writer_deployment claim {claim_id} was {result} by sanitized Pi runtime evidence."
        ),
    )


def _phase1_writer_claim_verified(
    report: Phase1WriterLiveQualificationReport,
    *,
    claim_id: str,
    tests_passed: bool,
) -> bool:
    if claim_id == "capability_observed":
        return report.deployed_module_observed
    if claim_id == "production_environment_verified":
        return report.host_ref.startswith("pi://") and report.pi_runtime_observed
    if claim_id == "lineage_verified":
        return bool(
            report.runtime_observation_sha256 and report.deployed_module_sha256
        )
    if claim_id in {
        "fail_closed_behavior_verified",
        "rollback_or_fallback_verified",
    }:
        return tests_passed
    if claim_id == "phase1_writer_runtime_deployed":
        return report.phase1_writer_runtime_deployed
    if claim_id == "guarded_writer_invocation_verified":
        return bool(
            tests_passed
            and report.deployed_module_lineage_verified
            and report.guarded_writer_surface_observed
        )
    if claim_id == "production_write_boundary_reviewed":
        return bool(
            tests_passed
            and report.deployed_module_lineage_verified
            and report.production_write_boundary_surface_observed
        )
    return False


def _junit_passed(path: Path) -> bool:
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    if not suites:
        return False
    return all(
        int(suite.attrib.get("failures", "0")) == 0
        and int(suite.attrib.get("errors", "0")) == 0
        and int(suite.attrib.get("tests", "0")) > 0
        for suite in suites
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Bridge a sanitized Pi CWA report into qualification bundles."
    )
    parser.add_argument("--report", required=True)
    parser.add_argument(
        "--kind",
        choices=("cwa", "mqtt", "pi", "phase1_writer"),
        default="cwa",
    )
    parser.add_argument("--test-evidence", required=True)
    parser.add_argument("--credential-rotation-receipt")
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--qualification-root-ref", required=True)
    parser.add_argument("--reviewer-ref", required=True)
    args = parser.parse_args(argv)

    if args.kind == "mqtt":
        report = load_mqtt_live_qualification_report(args.report)
        paths = write_mqtt_live_evidence_bundles(
            report,
            test_evidence_path=args.test_evidence,
            output_root=args.output_root,
            qualification_root_ref=args.qualification_root_ref,
            reviewer_ref=args.reviewer_ref,
            reviewed_at=datetime.now(timezone.utc),
        )
    elif args.kind == "pi":
        report = load_pi_live_qualification_report(args.report)
        paths = write_pi_live_evidence_bundles(
            report,
            test_evidence_path=args.test_evidence,
            output_root=args.output_root,
            qualification_root_ref=args.qualification_root_ref,
            reviewer_ref=args.reviewer_ref,
            reviewed_at=datetime.now(timezone.utc),
        )
    elif args.kind == "phase1_writer":
        report = load_phase1_writer_live_qualification_report(args.report)
        area_paths = write_phase1_writer_live_evidence_bundle(
            report,
            test_evidence_path=args.test_evidence,
            output_root=args.output_root,
            qualification_root_ref=args.qualification_root_ref,
            reviewer_ref=args.reviewer_ref,
            reviewed_at=datetime.now(timezone.utc),
        )
        paths = {"phase1_writer_deployment": area_paths}
    else:
        report = load_cwa_live_qualification_report(args.report)
        credential_rotation_receipt = (
            load_cwa_credential_rotation_receipt(
                args.credential_rotation_receipt
            )
            if args.credential_rotation_receipt
            else None
        )
        paths = write_cwa_live_evidence_bundles(
            report,
            credential_rotation_receipt=credential_rotation_receipt,
            test_evidence_path=args.test_evidence,
            output_root=args.output_root,
            qualification_root_ref=args.qualification_root_ref,
            reviewer_ref=args.reviewer_ref,
            reviewed_at=datetime.now(timezone.utc),
        )
    print(
        json.dumps(
            {
                area: {
                    "bundle_path": str(area_paths.bundle_path),
                    "source_package_path": str(area_paths.source_package_path),
                }
                for area, area_paths in paths.items()
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
