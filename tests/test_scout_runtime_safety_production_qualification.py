from __future__ import annotations

import json

import pytest

from scout_energy_models import aggregate_sha256, sha256_file
from scout_runtime_safety_production_qualification import (
    PRODUCTION_SAFETY_QUALIFICATION_REQUIRED_CLAIMS,
    PRODUCTION_SAFETY_CUTOVER_REVIEW_CONFIRMATION,
    PRODUCTION_SAFETY_CUTOVER_RELEASE_CLOSURE_CONFIRMATION,
    PRODUCTION_SAFETY_CUTOVER_RELEASE_HANDOFF_CONFIRMATION,
    REQUIRED_PRODUCTION_SAFETY_QUALIFICATION_AREAS,
    REQUIRED_PRODUCTION_SAFETY_QUALIFICATION_MODES,
    REQUIRED_PRODUCTION_SAFETY_THREAT_COVERAGE,
    ProductionSafetyQualificationCutoverAuthorizationReport,
    ProductionSafetyQualificationCutoverReleaseClosureReport,
    ProductionSafetyQualificationCutoverReleaseEffectReport,
    ProductionSafetyQualificationCutoverReleaseHandoffReport,
    ProductionSafetyQualificationDossierRerunReport,
    ProductionSafetyQualificationEvidenceBundle,
    ProductionSafetyQualificationEvidenceFulfillmentManifest,
    ProductionSafetyQualificationEvidenceFulfillmentSourcePackage,
    ProductionSafetyQualificationEvidencePackage,
    ProductionSafetyQualificationExternalActionPacket,
    ProductionSafetyQualificationExternalAuthorizationManifest,
    ProductionSafetyQualificationExternalAuthorizationReport,
    ProductionSafetyQualificationExternalInvocationManifest,
    ProductionSafetyQualificationExternalInvocationReport,
    ProductionSafetyQualificationExternalResultManifest,
    ProductionSafetyQualificationExternalResultEvidenceBridgeReport,
    ProductionSafetyQualificationExternalResultRemediationClosureReport,
    ProductionSafetyQualificationExternalResultReport,
    ProductionSafetyQualificationBoundary,
    ProductionSafetyQualificationReceipt,
    ProductionSafetyQualificationRemediationReadinessReport,
    ProductionSafetyQualificationThreatCoverageManifest,
    build_production_safety_qualification_evidence_fulfillment_manifest_from_external_results,
    build_production_safety_qualification_external_action_packet,
    evaluate_production_safety_qualification_cutover_authorization,
    evaluate_production_safety_qualification_cutover_release_closure,
    evaluate_production_safety_qualification_cutover_release_effect_intake,
    evaluate_production_safety_qualification_cutover_release_handoff,
    evaluate_production_safety_qualification_external_authorization,
    evaluate_production_safety_qualification_external_invocation,
    evaluate_production_safety_qualification_external_result_intake,
    evaluate_production_safety_qualification_external_result_remediation_closure,
    evaluate_production_safety_qualification_dossier_rerun_intake,
    evaluate_production_safety_qualification_evidence_fulfillment,
    evaluate_production_safety_qualification_remediation_readiness,
    evaluate_production_safety_qualification_threat_coverage,
    evaluate_production_safety_qualification_bundle,
    evaluate_production_safety_cutover_readiness,
    load_production_safety_cutover_readiness_audit,
    load_production_safety_qualification_cutover_authorization_report,
    load_production_safety_qualification_cutover_release_closure_report,
    load_production_safety_qualification_cutover_release_effect_report,
    load_production_safety_qualification_cutover_release_handoff_report,
    load_production_safety_qualification_dossier_rerun_report,
    load_production_safety_qualification_dossier_report,
    load_production_safety_qualification_evidence_fulfillment_manifest,
    load_production_safety_qualification_evidence_fulfillment_report,
    load_production_safety_qualification_evidence_fulfillment_source_integrity_report,
    load_production_safety_qualification_evidence_request_pack,
    load_production_safety_qualification_external_action_packet,
    load_production_safety_qualification_external_authorization_report,
    load_production_safety_qualification_external_invocation_report,
    load_production_safety_qualification_external_result_evidence_bridge_report,
    load_production_safety_qualification_external_result_remediation_closure_report,
    load_production_safety_qualification_external_result_report,
    load_production_safety_qualification_gap_plan,
    load_production_safety_qualification_remediation_readiness_report,
    load_production_safety_qualification_threat_coverage_audit,
    load_production_safety_qualification_threat_coverage_source_integrity_report,
    load_production_safety_qualification_source_integrity_report,
    load_production_safety_qualification_receipt_admission_decision,
    main,
    run_production_safety_qualification_dossier,
    run_production_safety_cutover_readiness_audit,
    evaluate_production_safety_qualification_gap_plan,
    build_production_safety_qualification_evidence_request_pack,
    verify_production_safety_qualification_evidence_fulfillment_source_integrity,
    verify_production_safety_qualification_threat_coverage_source_integrity,
    verify_production_safety_qualification_source_integrity,
    write_production_safety_qualification_cutover_authorization_report,
    write_production_safety_qualification_cutover_release_closure_report,
    write_production_safety_qualification_cutover_release_effect_report,
    write_production_safety_qualification_cutover_release_handoff_report,
    write_production_safety_qualification_dossier_report,
    write_production_safety_qualification_dossier_rerun_report,
    write_production_safety_qualification_evidence_fulfillment_report,
    write_production_safety_qualification_evidence_fulfillment_source_integrity_report,
    write_production_safety_qualification_evidence_request_pack,
    write_production_safety_qualification_external_action_packet,
    write_production_safety_qualification_external_authorization_report,
    write_production_safety_qualification_external_invocation_report,
    write_production_safety_qualification_external_result_evidence_bridge_report,
    write_production_safety_qualification_external_result_remediation_closure_report,
    write_production_safety_qualification_external_result_report,
    write_production_safety_qualification_gap_plan,
    write_production_safety_qualification_remediation_readiness_report,
    write_production_safety_qualification_threat_coverage_audit,
    write_production_safety_qualification_threat_coverage_source_integrity_report,
    write_production_safety_qualification_source_integrity_report,
    write_production_safety_qualification_receipt_admission_decision,
)


def _qualification_receipt_payload(area: str, index: int = 1) -> dict[str, object]:
    suffix = f"{area}-{index:02d}"
    return {
        "area": area,
        "source_provider": "scout_production_qualification",
        "source_path": f"prod://qualification/{suffix}/receipt",
        "status": "qualified",
        "qualification_ref": f"prod://qualification/{suffix}/evidence",
        "qualification_sha256": str(index) * 64,
        "reviewed_effect_boundary_ref": f"attestation://qualification/{suffix}/boundary",
        "reviewed_effect_boundary_sha256": "a" * 64,
        "operator_review_ref": f"operator://qualification/{suffix}/review",
        "operator_review_sha256": "b" * 64,
        "capability_observed": True,
        "production_environment_verified": True,
        "lineage_verified": True,
        "fail_closed_behavior_verified": True,
        "rollback_or_fallback_verified": True,
    }


def _qualification_bundle_payload(
    area: str,
    index: int = 1,
    *,
    omit_claim: str | None = None,
    reject_claim: str | None = None,
    stale_claim: str | None = None,
    future_claim: str | None = None,
) -> dict[str, object]:
    suffix = f"{area}-{index:02d}"
    claims = []
    for claim_index, claim_id in enumerate(
        PRODUCTION_SAFETY_QUALIFICATION_REQUIRED_CLAIMS[area],
        start=1,
    ):
        if claim_id == omit_claim:
            continue
        evidence_observed_at = (
            "2026-08-26T23:00:00+00:00"
            if claim_id == stale_claim
            else "2026-08-27T23:00:00+00:00"
        )
        reviewer_observed_at = (
            "2026-08-28T00:30:00+00:00"
            if claim_id == future_claim
            else "2026-08-27T23:30:00+00:00"
        )
        claims.append(
            {
                "claim_id": claim_id,
                "evidence_ref": f"prod://qualification/{suffix}/claims/{claim_id}",
                "evidence_sha256": str((claim_index % 9) + 1) * 64,
                "evidence_observed_at": (
                    "2026-08-28T00:30:00+00:00"
                    if claim_id == future_claim
                    else evidence_observed_at
                ),
                "reviewer_ref": f"operator://qualification/{suffix}/claims/{claim_id}",
                "reviewer_sha256": f"{claim_index % 16:x}" * 64,
                "reviewer_observed_at": reviewer_observed_at,
                "max_age_seconds": 7200,
                "accepted": claim_id != reject_claim,
            }
        )
    return {
        "area": area,
        "source_provider": "scout_production_qualification",
        "source_path": f"prod://qualification/{suffix}/bundle",
        "reference_time": "2026-08-28T00:00:00+00:00",
        "qualification_ref": f"prod://qualification/{suffix}/evidence",
        "qualification_sha256": str(index) * 64,
        "reviewed_effect_boundary_ref": f"attestation://qualification/{suffix}/boundary",
        "reviewed_effect_boundary_sha256": "a" * 64,
        "operator_review_ref": f"operator://qualification/{suffix}/review",
        "operator_review_sha256": "b" * 64,
        "claims": claims,
    }


def _qualification_bundle_and_package_payload(
    tmp_path,
    area: str = "live_provider_api",
    index: int = 1,
    **bundle_kwargs,
) -> tuple[dict[str, object], dict[str, object]]:
    bundle = _qualification_bundle_payload(area, index, **bundle_kwargs)
    artifacts = []
    for claim in bundle["claims"]:
        claim_id = str(claim["claim_id"])
        path = tmp_path / f"{claim_id}.json"
        path.write_text(
            json.dumps(
                {
                    "claim_id": claim_id,
                    "sanitized": True,
                    "runtime_safety_truth": False,
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        digest = sha256_file(path)
        claim["evidence_sha256"] = digest
        artifacts.append(
            {
                "evidence_ref": claim["evidence_ref"],
                "evidence_sha256": digest,
                "local_path": path.name,
                "redacted_or_sanitized": True,
            }
        )
    package = {
        "area": area,
        "source_provider": "scout_production_qualification",
        "source_path": f"prod://qualification/{area}-{index:02d}/source-package",
        "artifacts": artifacts,
    }
    return bundle, package


def _source_integrity_report_for_bundle(
    tmp_path,
    bundle: dict[str, object],
    package: dict[str, object],
):
    return verify_production_safety_qualification_source_integrity(
        bundle,
        package,
        root_path=tmp_path,
        source_path=f"{package['source_path']}/source-integrity",
    )


def _threat_coverage_manifest_payload(
    *,
    omit_threat: str | None = None,
    fail_threat: str | None = None,
    stale_threat: str | None = None,
    omit_mode: str | None = None,
    fail_mode: str | None = None,
    stale_mode: str | None = None,
) -> dict[str, object]:
    threat_cases = []
    for index, threat_id in enumerate(REQUIRED_PRODUCTION_SAFETY_THREAT_COVERAGE, start=1):
        if threat_id == omit_threat:
            continue
        threat_cases.append(
            {
                "threat_id": threat_id,
                "evidence_ref": f"prod://qualification/threats/{threat_id}",
                "evidence_sha256": f"{index % 16:x}" * 64,
                "evidence_observed_at": (
                    "2026-08-26T23:00:00+00:00"
                    if threat_id == stale_threat
                    else "2026-08-27T23:00:00+00:00"
                ),
                "reviewer_ref": f"operator://qualification/threats/{threat_id}",
                "reviewer_sha256": f"{(index + 1) % 16:x}" * 64,
                "reviewer_observed_at": "2026-08-27T23:30:00+00:00",
                "max_age_seconds": 7200,
                "mitigated": threat_id != fail_threat,
            }
        )
    qualification_modes = []
    for index, mode_id in enumerate(
        REQUIRED_PRODUCTION_SAFETY_QUALIFICATION_MODES,
        start=1,
    ):
        if mode_id == omit_mode:
            continue
        qualification_modes.append(
            {
                "mode_id": mode_id,
                "evidence_ref": f"prod://qualification/modes/{mode_id}",
                "evidence_sha256": f"{index % 16:x}" * 64,
                "evidence_observed_at": (
                    "2026-08-26T23:00:00+00:00"
                    if mode_id == stale_mode
                    else "2026-08-27T23:00:00+00:00"
                ),
                "reviewer_ref": f"operator://qualification/modes/{mode_id}",
                "reviewer_sha256": f"{(index + 2) % 16:x}" * 64,
                "reviewer_observed_at": "2026-08-27T23:30:00+00:00",
                "max_age_seconds": 7200,
                "passed": mode_id != fail_mode,
            }
        )
    return {
        "source_path": "prod://qualification/threat-coverage/manifest",
        "reference_time": "2026-08-28T00:00:00+00:00",
        "threat_cases": threat_cases,
        "qualification_modes": qualification_modes,
    }


def _threat_coverage_manifest_and_package_payload(
    tmp_path,
    **manifest_kwargs,
) -> tuple[dict[str, object], dict[str, object]]:
    manifest = _threat_coverage_manifest_payload(**manifest_kwargs)
    artifacts = []
    coverage_items = [
        *[
            ("threat", case)
            for case in manifest["threat_cases"]
        ],
        *[
            ("mode", case)
            for case in manifest["qualification_modes"]
        ],
    ]
    for coverage_type, case in coverage_items:
        case_id = str(case.get("threat_id") or case.get("mode_id"))
        path = tmp_path / f"{coverage_type}-{case_id}.json"
        path.write_text(
            json.dumps(
                {
                    "coverage_type": coverage_type,
                    "case_id": case_id,
                    "sanitized": True,
                    "runtime_safety_truth": False,
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        digest = sha256_file(path)
        case["evidence_sha256"] = digest
        artifacts.append(
            {
                "evidence_ref": case["evidence_ref"],
                "evidence_sha256": digest,
                "local_path": path.name,
                "redacted_or_sanitized": True,
            }
        )
    return (
        manifest,
        {
            "source_path": "prod://qualification/threat-coverage/source-package",
            "artifacts": artifacts,
        },
    )


def _dossier_manifest_payload(
    tmp_path,
    *,
    omit_area: str | None = None,
    mutate_package_area: str | None = None,
    omit_threat_coverage: bool = False,
    fail_threat: str | None = None,
) -> dict[str, object]:
    entries = []
    for index, area in enumerate(
        REQUIRED_PRODUCTION_SAFETY_QUALIFICATION_AREAS,
        start=1,
    ):
        if area == omit_area:
            continue
        bundle, package = _qualification_bundle_and_package_payload(
            tmp_path,
            area,
            index,
        )
        if area == mutate_package_area:
            package = {
                **package,
                "artifacts": [
                    {
                        **package["artifacts"][0],
                        "evidence_sha256": "f" * 64,
                    },
                    *package["artifacts"][1:],
                ],
            }
        bundle_path = tmp_path / f"{area}-bundle.json"
        package_path = tmp_path / f"{area}-package.json"
        bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
        package_path.write_text(json.dumps(package), encoding="utf-8")
        entries.append(
            {
                "area": area,
                "bundle_path": str(bundle_path),
                "source_package_path": str(package_path),
            }
        )
    payload: dict[str, object] = {
        "source_path": "prod://qualification/dossier/manifest",
        "source_root_path": str(tmp_path),
        "entries": entries,
    }
    if not omit_threat_coverage:
        threat_manifest, threat_package = _threat_coverage_manifest_and_package_payload(
            tmp_path,
            fail_threat=fail_threat,
        )
        threat_coverage_path = tmp_path / "threat-coverage-manifest.json"
        threat_package_path = tmp_path / "threat-coverage-package.json"
        threat_coverage_path.write_text(
            json.dumps(threat_manifest),
            encoding="utf-8",
        )
        threat_package_path.write_text(
            json.dumps(threat_package),
            encoding="utf-8",
        )
        payload["threat_coverage_path"] = str(threat_coverage_path)
        payload["threat_coverage_source_package_path"] = str(threat_package_path)
    return payload


def _evidence_request_row_key(row) -> str:
    return ":".join(
        [
            row.request_kind,
            row.area or "",
            row.threat_id or "",
            row.mode_id or "",
        ]
    )


def _fulfillment_manifest_payload(
    pack,
    *,
    omit_key: str | None = None,
    wrong_kind_key: str | None = None,
    reject_key: str | None = None,
    missing_review_key: str | None = None,
) -> dict[str, object]:
    submissions = []
    for index, row in enumerate(pack.rows, start=1):
        key = _evidence_request_row_key(row)
        if key == omit_key:
            continue
        reviewer_ref = (
            None
            if key == missing_review_key
            else f"operator://qualification/fulfillment/{index:02d}/review"
        )
        reviewer_sha256 = None if key == missing_review_key else f"{index % 16:x}" * 64
        submissions.append(
            {
                "request_kind": row.request_kind,
                "area": row.area,
                "threat_id": row.threat_id,
                "mode_id": row.mode_id,
                "submitted_artifact_kind": (
                    "unexpected_artifact"
                    if key == wrong_kind_key
                    else row.required_artifacts[0]
                ),
                "submitted_artifact_ref": (
                    f"prod://qualification/fulfillment/{index:02d}/"
                    f"{row.request_kind}"
                ),
                "submitted_artifact_sha256": f"{(index + 1) % 16:x}" * 64,
                "reviewer_ref": reviewer_ref,
                "reviewer_sha256": reviewer_sha256,
                "source_integrity_evidence_present": True,
                "max_age_metadata_present": True,
                "accepted": key != reject_key,
            }
        )
    return {
        "source_path": "prod://qualification/evidence-fulfillment/manifest",
        "request_pack_ref": pack.source_path,
        "request_pack_sha256": pack.sha256,
        "submissions": submissions,
    }


def _fulfillment_manifest_and_source_package_payload(
    tmp_path,
    pack,
    *,
    omit_key: str | None = None,
    wrong_kind_key: str | None = None,
    reject_key: str | None = None,
    missing_review_key: str | None = None,
) -> tuple[dict[str, object], dict[str, object]]:
    manifest = _fulfillment_manifest_payload(
        pack,
        omit_key=omit_key,
        wrong_kind_key=wrong_kind_key,
        reject_key=reject_key,
        missing_review_key=missing_review_key,
    )
    artifacts = []
    for index, submission in enumerate(manifest["submissions"], start=1):
        path = tmp_path / f"fulfillment-{index:02d}.json"
        path.write_text(
            json.dumps(
                {
                    "submitted_artifact_ref": submission["submitted_artifact_ref"],
                    "submitted_artifact_kind": submission["submitted_artifact_kind"],
                    "sanitized": True,
                    "runtime_safety_truth": False,
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        digest = sha256_file(path)
        submission["submitted_artifact_sha256"] = digest
        artifacts.append(
            {
                "submitted_artifact_ref": submission["submitted_artifact_ref"],
                "submitted_artifact_sha256": digest,
                "local_path": path.name,
                "redacted_or_sanitized": True,
            }
        )
    manifest_model = ProductionSafetyQualificationEvidenceFulfillmentManifest.model_validate(
        manifest
    )
    package = {
        "source_path": "prod://qualification/evidence-fulfillment/source-package",
        "fulfillment_manifest_ref": manifest_model.source_path,
        "fulfillment_manifest_sha256": aggregate_sha256(
            [manifest_model.model_dump(mode="json")]
        ),
        "artifacts": artifacts,
    }
    return manifest, package


def _source_verified_fulfillment_report(tmp_path, pack):
    manifest, source_package = _fulfillment_manifest_and_source_package_payload(
        tmp_path,
        pack,
    )
    source_report = (
        verify_production_safety_qualification_evidence_fulfillment_source_integrity(
            manifest,
            source_package,
            root_path=tmp_path,
        )
    )
    fulfillment = evaluate_production_safety_qualification_evidence_fulfillment(
        pack,
        manifest,
        source_integrity_report=source_report,
    )
    return manifest, source_package, source_report, fulfillment


def _external_authorization_row_key(row) -> str:
    return "|".join(
        [
            row.gap_kind,
            row.action,
            row.area or "",
            row.threat_id or "",
            row.mode_id or "",
        ]
    )


def _external_authorization_manifest_payload(
    packet,
    *,
    omit_key: str | None = None,
    wrong_kind_key: str | None = None,
    reject_key: str | None = None,
    expired_key: str | None = None,
    missing_operator_key: str | None = None,
) -> dict[str, object]:
    submissions = []
    for index, row in enumerate(packet.rows, start=1):
        key = _external_authorization_row_key(row)
        if key == omit_key:
            continue
        external_action_kind = row.external_action_kind
        if key == wrong_kind_key:
            external_action_kind = (
                "dossier_rerun"
                if row.external_action_kind != "dossier_rerun"
                else "provider_api_qualification"
            )
        operator_ref = (
            None
            if key == missing_operator_key
            else f"operator://qualification/external-auth/{index:02d}/identity"
        )
        operator_sha = None if operator_ref is None else f"{index % 16:x}" * 64
        submissions.append(
            {
                "gap_kind": row.gap_kind,
                "action": row.action,
                "external_action_kind": external_action_kind,
                "area": row.area,
                "threat_id": row.threat_id,
                "mode_id": row.mode_id,
                "authorized": key != reject_key,
                "operator_identity_ref": operator_ref,
                "operator_identity_sha256": operator_sha,
                "authorization_ref": (
                    f"attestation://qualification/external-auth/{index:02d}/approval"
                ),
                "authorization_sha256": f"{(index + 1) % 16:x}" * 64,
                "reviewed_effect_boundary_ref": (
                    f"attestation://qualification/external-auth/{index:02d}/boundary"
                ),
                "reviewed_effect_boundary_sha256": f"{(index + 2) % 16:x}" * 64,
                "idempotency_key": f"external-auth-{index:02d}",
                "authorization_observed_at": "2026-08-27T23:00:00+00:00",
                "expires_at": (
                    "2026-08-27T23:30:00+00:00"
                    if key == expired_key
                    else "2026-08-28T02:00:00+00:00"
                ),
            }
        )
    return {
        "source_path": "prod://qualification/external-authorization/manifest",
        "external_action_packet_ref": packet.source_path,
        "external_action_packet_sha256": packet.sha256,
        "reference_time": "2026-08-28T00:00:00+00:00",
        "submissions": submissions,
    }


def _external_invocation_row_key(row) -> str:
    return "|".join(
        [
            row.gap_kind,
            row.action,
            row.area or "",
            row.threat_id or "",
            row.mode_id or "",
        ]
    )


def _external_invocation_manifest_payload(
    authorization,
    *,
    omit_key: str | None = None,
    wrong_kind_key: str | None = None,
    no_request_key: str | None = None,
    no_confirmation_key: str | None = None,
    missing_executor_key: str | None = None,
) -> dict[str, object]:
    requests = []
    for index, row in enumerate(authorization.rows, start=1):
        key = _external_invocation_row_key(row)
        if key == omit_key:
            continue
        external_action_kind = row.external_action_kind
        if key == wrong_kind_key:
            external_action_kind = (
                "dossier_rerun"
                if row.external_action_kind != "dossier_rerun"
                else "provider_api_qualification"
            )
        executor_ref = (
            None
            if key == missing_executor_key
            else f"provider://qualification/executor/{index:02d}"
        )
        executor_sha = None if executor_ref is None else f"{(index + 3) % 16:x}" * 64
        requests.append(
            {
                "gap_kind": row.gap_kind,
                "action": row.action,
                "external_action_kind": external_action_kind,
                "area": row.area,
                "threat_id": row.threat_id,
                "mode_id": row.mode_id,
                "invocation_requested": key != no_request_key,
                "operator_confirmation": key != no_confirmation_key,
                "operator_identity_ref": row.operator_identity_ref,
                "operator_identity_sha256": row.operator_identity_sha256,
                "authorization_ref": row.authorization_ref,
                "authorization_sha256": row.authorization_sha256,
                "reviewed_effect_boundary_ref": row.reviewed_effect_boundary_ref,
                "reviewed_effect_boundary_sha256": (
                    row.reviewed_effect_boundary_sha256
                ),
                "external_executor_ref": executor_ref,
                "external_executor_sha256": executor_sha,
                "executor_invocation_ref": (
                    f"attestation://qualification/invocation/{index:02d}"
                ),
                "executor_invocation_sha256": f"{(index + 4) % 16:x}" * 64,
                "authorization_idempotency_key": row.idempotency_key,
                "invocation_idempotency_key": f"external-invoke-{index:02d}",
                "requested_at": "2026-08-28T00:05:00+00:00",
            }
        )
    return {
        "source_path": "prod://qualification/external-invocation/manifest",
        "external_authorization_report_ref": authorization.source_path,
        "external_authorization_report_sha256": authorization.sha256,
        "reference_time": "2026-08-28T00:10:00+00:00",
        "requests": requests,
    }


def _external_result_row_key(row) -> str:
    return "|".join(
        [
            row.gap_kind,
            row.action,
            row.area or "",
            row.threat_id or "",
            row.mode_id or "",
        ]
    )


def _external_result_request_key(row) -> str:
    return "|".join(
        [
            row.source_gap_kind or "",
            row.action or "",
            row.area or "",
            row.threat_id or "",
            row.mode_id or "",
        ]
    )


def _external_result_artifact_ref(index: int, row) -> str:
    return (
        f"prod://qualification/external-result-artifact/"
        f"{index:02d}/{row.request_kind}"
    )


def _external_result_local_artifact_files(tmp_path, pack):
    hashes_by_request_key: dict[str, str] = {}
    paths_by_artifact_ref = {}
    for index, row in enumerate(pack.rows, start=1):
        artifact_ref = _external_result_artifact_ref(index, row)
        path = tmp_path / f"external-result-artifact-{index:02d}.json"
        path.write_text(
            json.dumps(
                {
                    "request_kind": row.request_kind,
                    "area": row.area,
                    "threat_id": row.threat_id,
                    "mode_id": row.mode_id,
                    "sanitized": True,
                    "runtime_safety_truth": False,
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        hashes_by_request_key[_evidence_request_row_key(row)] = sha256_file(path)
        paths_by_artifact_ref[artifact_ref] = path
    return hashes_by_request_key, paths_by_artifact_ref


def _external_result_source_package_payload_for_bridge(
    bridge,
    paths_by_artifact_ref,
    *,
    wrong_hash_ref: str | None = None,
) -> dict[str, object]:
    assert bridge.fulfillment_manifest is not None
    artifacts = []
    for submission in bridge.fulfillment_manifest.submissions:
        artifacts.append(
            {
                "submitted_artifact_ref": submission.submitted_artifact_ref,
                "submitted_artifact_sha256": (
                    "f" * 64
                    if submission.submitted_artifact_ref == wrong_hash_ref
                    else submission.submitted_artifact_sha256
                ),
                "local_path": paths_by_artifact_ref[
                    submission.submitted_artifact_ref
                ].name,
                "redacted_or_sanitized": True,
            }
        )
    return {
        "source_path": "prod://qualification/external-result/source-package",
        "fulfillment_manifest_ref": bridge.fulfillment_manifest.source_path,
        "fulfillment_manifest_sha256": aggregate_sha256(
            [bridge.fulfillment_manifest.model_dump(mode="json")]
        ),
        "artifacts": artifacts,
    }


def _ready_external_result_remediation_closure(
    tmp_path,
    *,
    omit_area: str = "field_device_validator",
    source_path: str = "prod://qualification/external-result-closure/ready",
):
    report = run_production_safety_qualification_dossier(
        _dossier_manifest_payload(tmp_path, omit_area=omit_area),
    )
    plan = evaluate_production_safety_qualification_gap_plan(report)
    pack = build_production_safety_qualification_evidence_request_pack(plan)
    _manifest, _source_package, _source_report, fulfillment = (
        _source_verified_fulfillment_report(tmp_path, pack)
    )
    remediation = evaluate_production_safety_qualification_remediation_readiness(
        plan,
        pack,
        fulfillment,
    )
    packet = build_production_safety_qualification_external_action_packet(remediation)
    authorization = evaluate_production_safety_qualification_external_authorization(
        packet,
        _external_authorization_manifest_payload(packet),
    )
    invocation = evaluate_production_safety_qualification_external_invocation(
        authorization,
        _external_invocation_manifest_payload(authorization),
    )
    artifact_hashes, artifact_paths = _external_result_local_artifact_files(
        tmp_path,
        pack,
    )
    result = evaluate_production_safety_qualification_external_result_intake(
        invocation,
        _external_result_manifest_payload(
            invocation,
            request_pack=pack,
            artifact_hashes_by_request_key=artifact_hashes,
        ),
    )
    bridge = build_production_safety_qualification_evidence_fulfillment_manifest_from_external_results(
        pack,
        result,
    )
    source_package = _external_result_source_package_payload_for_bridge(
        bridge,
        artifact_paths,
    )
    return evaluate_production_safety_qualification_external_result_remediation_closure(
        plan,
        pack,
        bridge,
        source_package,
        root_path=tmp_path,
        source_path=source_path,
    )


def _cutover_authorization_manifest_payload(
    rerun,
    *,
    authorized: bool = True,
    omit_operator: bool = False,
    expired: bool = False,
    confirmation_phrase: str | None = PRODUCTION_SAFETY_CUTOVER_REVIEW_CONFIRMATION,
) -> dict[str, object]:
    operator_ref = (
        None
        if omit_operator
        else "operator://qualification/cutover-authorization/operator"
    )
    return {
        "source_path": "prod://qualification/cutover-authorization/manifest",
        "dossier_rerun_ref": rerun.source_path,
        "dossier_rerun_sha256": rerun.sha256,
        "reference_time": "2026-08-28T00:00:00+00:00",
        "authorized": authorized,
        "operator_identity_ref": operator_ref,
        "operator_identity_sha256": None if operator_ref is None else "1" * 64,
        "authorization_ref": "operator://qualification/cutover-authorization/review",
        "authorization_sha256": "2" * 64,
        "reviewed_effect_boundary_ref": (
            "attestation://qualification/cutover-authorization/boundary"
        ),
        "reviewed_effect_boundary_sha256": "3" * 64,
        "rollback_plan_ref": "deployment://qualification/cutover/rollback-plan",
        "rollback_plan_sha256": "4" * 64,
        "production_change_request_ref": (
            "deployment://qualification/cutover/change-request"
        ),
        "production_change_request_sha256": "5" * 64,
        "idempotency_key": "cutover-authorization-review-001",
        "authorization_observed_at": "2026-08-27T23:45:00+00:00",
        "expires_at": (
            "2026-08-27T23:50:00+00:00"
            if expired
            else "2026-08-28T02:00:00+00:00"
        ),
        "explicit_confirmation_phrase": confirmation_phrase,
    }


def _ready_dossier_rerun_report(
    tmp_path,
    *,
    omit_area: str = "field_device_validator",
    source_path: str = "prod://qualification/dossier-rerun/ready",
):
    closure = _ready_external_result_remediation_closure(
        tmp_path,
        omit_area=omit_area,
        source_path=f"{source_path}/closure",
    )
    return evaluate_production_safety_qualification_dossier_rerun_intake(
        closure,
        _dossier_manifest_payload(tmp_path),
        source_integrity_output_dir=tmp_path / "cutover-rerun-source-integrity",
        admission_output_dir=tmp_path / "cutover-rerun-admission",
        receipt_output_dir=tmp_path / "cutover-rerun-receipts",
        source_path=source_path,
    )


def _recorded_cutover_authorization_report(
    tmp_path,
    *,
    omit_area: str = "field_device_validator",
    source_path: str = "prod://qualification/cutover-authorization/ready",
):
    rerun = _ready_dossier_rerun_report(
        tmp_path,
        omit_area=omit_area,
        source_path=f"{source_path}/rerun",
    )
    return evaluate_production_safety_qualification_cutover_authorization(
        rerun,
        _cutover_authorization_manifest_payload(rerun),
        source_path=source_path,
    )


def _cutover_release_handoff_manifest_payload(
    authorization,
    *,
    include_request: bool = True,
    release_handoff_requested: bool = True,
    operator_confirmation: bool = True,
    omit_release_executor: bool = False,
    wrong_operator: bool = False,
    requested_after_reference: bool = False,
    confirmation_phrase: (
        str | None
    ) = PRODUCTION_SAFETY_CUTOVER_RELEASE_HANDOFF_CONFIRMATION,
) -> dict[str, object]:
    request = None
    if include_request:
        operator_ref = (
            "operator://qualification/cutover-release/other-operator"
            if wrong_operator
            else authorization.operator_identity_ref
        )
        request = {
            "release_handoff_requested": release_handoff_requested,
            "operator_confirmation": operator_confirmation,
            "operator_identity_ref": operator_ref,
            "operator_identity_sha256": authorization.operator_identity_sha256,
            "authorization_ref": authorization.authorization_ref,
            "authorization_sha256": authorization.authorization_sha256,
            "reviewed_effect_boundary_ref": (
                authorization.reviewed_effect_boundary_ref
            ),
            "reviewed_effect_boundary_sha256": (
                authorization.reviewed_effect_boundary_sha256
            ),
            "rollback_plan_ref": authorization.rollback_plan_ref,
            "rollback_plan_sha256": authorization.rollback_plan_sha256,
            "production_change_request_ref": (
                authorization.production_change_request_ref
            ),
            "production_change_request_sha256": (
                authorization.production_change_request_sha256
            ),
            "release_executor_ref": (
                None
                if omit_release_executor
                else "deployment://qualification/cutover-release/executor"
            ),
            "release_executor_sha256": (
                None if omit_release_executor else "6" * 64
            ),
            "release_invocation_ref": (
                "attestation://qualification/cutover-release/invocation"
            ),
            "release_invocation_sha256": "7" * 64,
            "cutover_authorization_idempotency_key": authorization.idempotency_key,
            "handoff_idempotency_key": "cutover-release-handoff-001",
            "requested_at": (
                "2026-08-28T00:30:00+00:00"
                if requested_after_reference
                else "2026-08-28T00:05:00+00:00"
            ),
            "explicit_confirmation_phrase": confirmation_phrase,
        }
    return {
        "source_path": "prod://qualification/cutover-release/handoff-manifest",
        "cutover_authorization_report_ref": authorization.source_path,
        "cutover_authorization_report_sha256": authorization.sha256,
        "reference_time": "2026-08-28T00:10:00+00:00",
        "request": request,
    }


def _recorded_cutover_release_handoff_report(
    tmp_path,
    *,
    omit_area: str = "field_device_validator",
    source_path: str = "prod://qualification/cutover-release/handoff-ready",
):
    authorization = _recorded_cutover_authorization_report(
        tmp_path,
        omit_area=omit_area,
        source_path=f"{source_path}/authorization",
    )
    return evaluate_production_safety_qualification_cutover_release_handoff(
        authorization,
        _cutover_release_handoff_manifest_payload(authorization),
        source_path=source_path,
    )


def _cutover_release_effect_manifest_payload(
    handoff,
    *,
    include_receipt: bool = True,
    accepted: bool = True,
    source_integrity: bool = True,
    max_age: bool = True,
    completed: bool = True,
    omit_execution: bool = False,
    wrong_executor: bool = False,
    observed_after_reference: bool = False,
) -> dict[str, object]:
    receipt = None
    if include_receipt:
        receipt = {
            "source_path": "prod://qualification/cutover-release/effect-receipt",
            "cutover_release_handoff_report_ref": handoff.source_path,
            "cutover_release_handoff_report_sha256": handoff.sha256,
            "release_executor_ref": (
                "deployment://qualification/cutover-release/other-executor"
                if wrong_executor
                else handoff.release_executor_ref
            ),
            "release_executor_sha256": handoff.release_executor_sha256,
            "release_invocation_ref": handoff.release_invocation_ref,
            "release_invocation_sha256": handoff.release_invocation_sha256,
            "handoff_idempotency_key": handoff.handoff_idempotency_key,
            "release_execution_ref": (
                None
                if omit_execution
                else "deployment://qualification/cutover-release/execution"
            ),
            "release_execution_sha256": None if omit_execution else "8" * 64,
            "release_result_ref": "prod://qualification/cutover-release/result",
            "release_result_sha256": "9" * 64,
            "reviewer_ref": "operator://qualification/cutover-release/review",
            "reviewer_sha256": "a" * 64,
            "release_observed_at": (
                "2026-08-28T01:05:00+00:00"
                if observed_after_reference
                else "2026-08-28T00:20:00+00:00"
            ),
            "accepted": accepted,
            "executor_reported_release_completed": completed,
            "source_integrity_evidence_present": source_integrity,
            "max_age_metadata_present": max_age,
        }
    return {
        "source_path": "prod://qualification/cutover-release/effect-manifest",
        "cutover_release_handoff_report_ref": handoff.source_path,
        "cutover_release_handoff_report_sha256": handoff.sha256,
        "reference_time": "2026-08-28T00:40:00+00:00",
        "receipt": receipt,
    }


def _cutover_release_closure_manifest_payload(
    effect,
    *,
    include_review: bool = True,
    accepted: bool = True,
    source_integrity: bool = True,
    max_age: bool = True,
    confirmation: bool = True,
    wrong_result: bool = False,
    wrong_phrase: bool = False,
    expired: bool = False,
    reviewed_after_reference: bool = False,
) -> dict[str, object]:
    review = None
    if include_review:
        handoff = effect.cutover_release_handoff_report
        review = {
            "source_path": "prod://qualification/cutover-release/closure-review",
            "cutover_release_effect_report_ref": effect.source_path,
            "cutover_release_effect_report_sha256": effect.sha256,
            "release_executor_ref": effect.release_executor_ref,
            "release_executor_sha256": effect.release_executor_sha256,
            "release_invocation_ref": effect.release_invocation_ref,
            "release_invocation_sha256": effect.release_invocation_sha256,
            "handoff_idempotency_key": effect.handoff_idempotency_key,
            "release_execution_ref": effect.release_execution_ref,
            "release_execution_sha256": effect.release_execution_sha256,
            "release_result_ref": (
                "prod://qualification/cutover-release/other-result"
                if wrong_result
                else effect.release_result_ref
            ),
            "release_result_sha256": effect.release_result_sha256,
            "release_effect_reviewer_ref": effect.reviewer_ref,
            "release_effect_reviewer_sha256": effect.reviewer_sha256,
            "closure_reviewer_ref": "operator://qualification/cutover-release/closure-reviewer",
            "closure_reviewer_sha256": "b" * 64,
            "rollback_plan_ref": handoff.rollback_plan_ref,
            "rollback_plan_sha256": handoff.rollback_plan_sha256,
            "production_change_request_ref": handoff.production_change_request_ref,
            "production_change_request_sha256": handoff.production_change_request_sha256,
            "closure_reviewed_at": (
                "2026-08-28T01:20:00+00:00"
                if reviewed_after_reference
                else "2026-08-28T00:30:00+00:00"
            ),
            "expires_at": (
                "2026-08-28T00:35:00+00:00"
                if expired
                else "2026-08-28T01:30:00+00:00"
            ),
            "accepted": accepted,
            "closure_reviewer_confirmation": confirmation,
            "source_integrity_evidence_present": source_integrity,
            "max_age_metadata_present": max_age,
            "explicit_confirmation_phrase": (
                "CLOSE THE WRONG CUTOVER REVIEW"
                if wrong_phrase
                else PRODUCTION_SAFETY_CUTOVER_RELEASE_CLOSURE_CONFIRMATION
            ),
        }
    return {
        "source_path": "prod://qualification/cutover-release/closure-manifest",
        "cutover_release_effect_report_ref": effect.source_path,
        "cutover_release_effect_report_sha256": effect.sha256,
        "reference_time": "2026-08-28T00:40:00+00:00",
        "closure_review": review,
    }


def _recorded_cutover_release_effect_report(
    tmp_path,
    *,
    omit_area: str = "field_device_validator",
    source_path: str = "prod://qualification/cutover-release/effect-ready",
):
    handoff = _recorded_cutover_release_handoff_report(
        tmp_path,
        omit_area=omit_area,
        source_path=f"{source_path}/handoff",
    )
    return evaluate_production_safety_qualification_cutover_release_effect_intake(
        handoff,
        _cutover_release_effect_manifest_payload(handoff),
        source_path=source_path,
    )


def _external_result_provided_artifacts(
    pack,
    result_key: str,
    *,
    artifact_hashes_by_request_key: dict[str, str] | None = None,
) -> list[dict[str, object]]:
    if pack is None:
        return []
    artifacts = []
    for index, row in enumerate(pack.rows, start=1):
        if _external_result_request_key(row) != result_key:
            continue
        request_key = _evidence_request_row_key(row)
        artifacts.append(
            {
                "submitted_artifact_kind": row.required_artifacts[0],
                "submitted_artifact_ref": _external_result_artifact_ref(index, row),
                "submitted_artifact_sha256": (
                    artifact_hashes_by_request_key[request_key]
                    if artifact_hashes_by_request_key
                    else f"{(index + 8) % 16:x}" * 64
                ),
                "reviewer_ref": (
                    f"operator://qualification/external-result-artifact/"
                    f"{index:02d}/review"
                ),
                "reviewer_sha256": f"{(index + 9) % 16:x}" * 64,
                "source_integrity_evidence_present": True,
                "max_age_metadata_present": True,
                "accepted": True,
            }
        )
    return artifacts


def _external_result_manifest_payload(
    invocation,
    *,
    request_pack=None,
    artifact_hashes_by_request_key: dict[str, str] | None = None,
    omit_key: str | None = None,
    wrong_executor_key: str | None = None,
    reject_key: str | None = None,
    unverified_source_key: str | None = None,
    missing_reviewer_key: str | None = None,
    reject_provided_artifacts_key: str | None = None,
) -> dict[str, object]:
    receipts = []
    for index, row in enumerate(invocation.rows, start=1):
        key = _external_result_row_key(row)
        if key == omit_key:
            continue
        executor_ref = row.external_executor_ref
        executor_sha = row.external_executor_sha256
        if key == wrong_executor_key:
            executor_ref = f"provider://qualification/executor/wrong-{index:02d}"
            executor_sha = "e" * 64
        reviewer_ref = (
            None
            if key == missing_reviewer_key
            else f"operator://qualification/result/{index:02d}/review"
        )
        reviewer_sha = None if reviewer_ref is None else f"{(index + 6) % 16:x}" * 64
        provided_artifacts = _external_result_provided_artifacts(
            request_pack,
            key,
            artifact_hashes_by_request_key=artifact_hashes_by_request_key,
        )
        if key == reject_provided_artifacts_key:
            provided_artifacts = [
                {
                    **artifact,
                    "accepted": False,
                }
                for artifact in provided_artifacts
            ]
        receipts.append(
            {
                "gap_kind": row.gap_kind,
                "action": row.action,
                "external_action_kind": row.external_action_kind,
                "area": row.area,
                "threat_id": row.threat_id,
                "mode_id": row.mode_id,
                "accepted": key != reject_key,
                "external_executor_ref": executor_ref,
                "external_executor_sha256": executor_sha,
                "executor_invocation_ref": row.executor_invocation_ref,
                "executor_invocation_sha256": row.executor_invocation_sha256,
                "result_artifact_kind": "production_qualification_external_result",
                "result_ref": f"prod://qualification/result/{index:02d}",
                "result_sha256": f"{(index + 5) % 16:x}" * 64,
                "result_observed_at": "2026-08-28T00:20:00+00:00",
                "reviewer_ref": reviewer_ref,
                "reviewer_sha256": reviewer_sha,
                "provided_artifacts": provided_artifacts,
                "source_integrity_evidence_present": key != unverified_source_key,
                "max_age_metadata_present": True,
            }
        )
    return {
        "source_path": "prod://qualification/external-result/manifest",
        "external_invocation_report_ref": invocation.source_path,
        "external_invocation_report_sha256": invocation.sha256,
        "receipts": receipts,
    }



def test_production_safety_cutover_readiness_blocks_missing_required_areas() -> None:
    audit = evaluate_production_safety_cutover_readiness([])

    assert audit.status == "blocked_missing_required_qualification"
    assert audit.ready_for_production_cutover is False
    assert audit.required_areas == list(REQUIRED_PRODUCTION_SAFETY_QUALIFICATION_AREAS)
    assert audit.missing_areas == list(REQUIRED_PRODUCTION_SAFETY_QUALIFICATION_AREAS)
    assert audit.failed_areas == []
    assert len(audit.rows) == len(REQUIRED_PRODUCTION_SAFETY_QUALIFICATION_AREAS)
    assert all(row.status == "missing" for row in audit.rows)
    assert audit.external_call_performed_by_audit is False
    assert audit.credential_material_loaded_by_audit is False
    assert audit.outbound_transport_invoked_by_audit is False
    assert audit.hardware_control_performed_by_audit is False
    assert audit.safety_api_called is False
    assert audit.runtime_safety_truth_mutated is False


def test_production_safety_cutover_readiness_requires_all_qualified_receipts() -> None:
    receipts = [
        _qualification_receipt_payload(area, index)
        for index, area in enumerate(
            REQUIRED_PRODUCTION_SAFETY_QUALIFICATION_AREAS,
            start=1,
        )
    ]

    audit = evaluate_production_safety_cutover_readiness(
        receipts,
        source_path="prod://qualification/cutover/audit-001",
    )

    assert audit.status == "ready_for_production_cutover"
    assert audit.ready_for_production_cutover is True
    assert audit.missing_areas == []
    assert audit.failed_areas == []
    assert all(row.qualified_for_cutover for row in audit.rows)
    assert {
        row.area for row in audit.rows
    } == set(REQUIRED_PRODUCTION_SAFETY_QUALIFICATION_AREAS)
    assert audit.external_call_performed_by_audit is False
    assert audit.safety_api_called is False
    assert audit.phase1_l0_l4_state_mutated is False
    assert audit.runtime_safety_truth_mutated is False


def test_production_safety_cutover_readiness_fails_closed_for_bad_receipts() -> None:
    partial = [
        _qualification_receipt_payload(area, index)
        for index, area in enumerate(
            REQUIRED_PRODUCTION_SAFETY_QUALIFICATION_AREAS,
            start=1,
        )
    ]
    partial[0] = {
        **partial[0],
        "status": "failed",
        "capability_observed": False,
    }

    audit = evaluate_production_safety_cutover_readiness(partial)

    assert audit.status == "blocked_failed_required_qualification"
    assert audit.ready_for_production_cutover is False
    assert audit.missing_areas == []
    assert audit.failed_areas == ["live_provider_api"]
    assert audit.rows[0].qualified_for_cutover is False

    with pytest.raises(ValueError, match="cannot embed credentials or raw payloads"):
        ProductionSafetyQualificationReceipt(
            **{
                **_qualification_receipt_payload("transport_client"),
                "credential_material_embedded": True,
            }
        )
    with pytest.raises(ValueError, match="cannot mutate safety runtime"):
        ProductionSafetyQualificationReceipt(
            **{
                **_qualification_receipt_payload("phase1_writer_deployment"),
                "safety_api_called_by_qualifier": True,
            }
        )
    with pytest.raises(ValueError, match="cannot perform effects"):
        ProductionSafetyQualificationBoundary(external_call_performed_by_audit=True)


def test_production_safety_cutover_audit_round_trips_json_artifact(tmp_path) -> None:
    receipt_paths = []
    for index, area in enumerate(
        REQUIRED_PRODUCTION_SAFETY_QUALIFICATION_AREAS,
        start=1,
    ):
        path = tmp_path / f"{area}.json"
        path.write_text(
            json.dumps(_qualification_receipt_payload(area, index)),
            encoding="utf-8",
        )
        receipt_paths.append(path)

    output_path = tmp_path / "cutover-readiness-audit.json"

    audit = run_production_safety_cutover_readiness_audit(
        receipt_paths,
        output_path=output_path,
        source_path="prod://qualification/cutover/audit-002",
    )
    loaded = load_production_safety_cutover_readiness_audit(output_path)

    assert output_path.exists()
    assert audit == loaded
    assert loaded.status == "ready_for_production_cutover"
    assert loaded.ready_for_production_cutover is True
    assert all(row.receipt_sha256 for row in loaded.rows)
    assert loaded.external_call_performed_by_audit is False
    assert loaded.credential_material_loaded_by_audit is False
    assert loaded.raw_payload_loaded_by_audit is False
    assert loaded.runtime_safety_truth_mutated is False


def test_production_safety_cutover_cli_writes_blocked_missing_audit(tmp_path) -> None:
    output_path = tmp_path / "blocked-cutover-readiness-audit.json"

    exit_code = main(["--output", str(output_path)])
    loaded = load_production_safety_cutover_readiness_audit(output_path)

    assert exit_code == 0
    assert loaded.status == "blocked_missing_required_qualification"
    assert loaded.ready_for_production_cutover is False
    assert loaded.missing_areas == list(REQUIRED_PRODUCTION_SAFETY_QUALIFICATION_AREAS)
    assert loaded.external_call_performed_by_audit is False
    assert loaded.safety_api_called is False
    assert loaded.outbound_transport_invoked_by_audit is False
    assert loaded.hardware_control_performed_by_audit is False


def test_production_safety_qualification_bundle_admits_area_specific_receipts(
    tmp_path,
) -> None:
    decisions = []
    for index, area in enumerate(
        REQUIRED_PRODUCTION_SAFETY_QUALIFICATION_AREAS,
        start=1,
    ):
        bundle, package = _qualification_bundle_and_package_payload(
            tmp_path,
            area,
            index,
        )
        decisions.append(
            evaluate_production_safety_qualification_bundle(
                bundle,
                source_integrity_report=_source_integrity_report_for_bundle(
                    tmp_path,
                    bundle,
                    package,
                ),
            )
        )

    assert all(decision.status == "qualification_receipt_accepted" for decision in decisions)
    assert all(decision.ready_for_cutover_receipt for decision in decisions)
    assert all(decision.receipt.status == "qualified" for decision in decisions)
    assert all(
        decision.required_claims
        == list(PRODUCTION_SAFETY_QUALIFICATION_REQUIRED_CLAIMS[decision.area])
        for decision in decisions
    )

    audit = evaluate_production_safety_cutover_readiness(
        [decision.receipt for decision in decisions],
        source_path="prod://qualification/cutover/from-admitted-receipts",
    )

    assert audit.status == "ready_for_production_cutover"
    assert audit.ready_for_production_cutover is True

    output_path = tmp_path / "admission-decision.json"
    stored = write_production_safety_qualification_receipt_admission_decision(
        decisions[0],
        output_path,
    )
    loaded = load_production_safety_qualification_receipt_admission_decision(
        output_path
    )

    assert stored == decisions[0]
    assert loaded == decisions[0]


def test_production_safety_qualification_bundle_blocks_missing_area_claims(
    tmp_path,
) -> None:
    blocked_bundle, blocked_package = _qualification_bundle_and_package_payload(
        tmp_path,
        "live_provider_api",
        omit_claim="provider_api_execution_observed",
    )
    blocked = evaluate_production_safety_qualification_bundle(
        blocked_bundle,
        source_integrity_report=_source_integrity_report_for_bundle(
            tmp_path,
            blocked_bundle,
            blocked_package,
        ),
    )
    qualified_receipts = []
    for index, area in enumerate(
        REQUIRED_PRODUCTION_SAFETY_QUALIFICATION_AREAS[1:],
        start=2,
    ):
        bundle, package = _qualification_bundle_and_package_payload(
            tmp_path,
            area,
            index,
        )
        qualified_receipts.append(
            evaluate_production_safety_qualification_bundle(
                bundle,
                source_integrity_report=_source_integrity_report_for_bundle(
                    tmp_path,
                    bundle,
                    package,
                ),
            ).receipt
        )

    audit = evaluate_production_safety_cutover_readiness(
        [blocked.receipt, *qualified_receipts],
    )

    assert blocked.status == "blocked_missing_required_claims"
    assert blocked.ready_for_cutover_receipt is False
    assert blocked.receipt.status == "blocked"
    assert blocked.missing_claims == ["provider_api_execution_observed"]
    assert audit.status == "blocked_failed_required_qualification"
    assert audit.failed_areas == ["live_provider_api"]


def test_production_safety_qualification_bundle_blocks_stale_claims(tmp_path) -> None:
    bundle, package = _qualification_bundle_and_package_payload(
        tmp_path,
        "resident_freshness_attestor",
        stale_claim="freshness_window_enforced",
    )
    stale = evaluate_production_safety_qualification_bundle(
        bundle,
        source_integrity_report=_source_integrity_report_for_bundle(
            tmp_path,
            bundle,
            package,
        ),
    )

    assert stale.status == "blocked_stale_required_claims"
    assert stale.ready_for_cutover_receipt is False
    assert stale.receipt.status == "blocked"
    assert stale.stale_claims == ["freshness_window_enforced"]
    assert "stale_required_claim:freshness_window_enforced" in stale.receipt.notes


def test_production_safety_qualification_bundle_blocks_without_source_integrity(
    tmp_path,
) -> None:
    bundle, _package = _qualification_bundle_and_package_payload(
        tmp_path,
        "transport_client",
    )

    decision = evaluate_production_safety_qualification_bundle(bundle)

    assert decision.status == "blocked_source_integrity_unverified"
    assert decision.ready_for_cutover_receipt is False
    assert decision.receipt.status == "blocked"
    assert decision.source_integrity_verified is False
    assert decision.unverified_source_claims == list(
        PRODUCTION_SAFETY_QUALIFICATION_REQUIRED_CLAIMS["transport_client"]
    )


def test_production_safety_qualification_bundle_blocks_rejected_claims_and_effects(
    tmp_path,
) -> None:
    bundle, package = _qualification_bundle_and_package_payload(
        tmp_path,
        "outbound_delivery",
        reject_claim="gateway_ack_rejected_as_insufficient",
    )
    rejected = evaluate_production_safety_qualification_bundle(
        bundle,
        source_integrity_report=_source_integrity_report_for_bundle(
            tmp_path,
            bundle,
            package,
        ),
    )

    assert rejected.status == "blocked_rejected_required_claims"
    assert rejected.ready_for_cutover_receipt is False
    assert rejected.receipt.status == "blocked"
    assert rejected.rejected_claims == ["gateway_ack_rejected_as_insufficient"]

    with pytest.raises(ValueError, match="qualification bundle admission cannot perform effects"):
        ProductionSafetyQualificationEvidenceBundle(
            **{
                **_qualification_bundle_payload("pi_hardware"),
                "external_call_performed_by_admission": True,
            }
        )
    with pytest.raises(ValueError, match="cannot be after reference_time"):
        ProductionSafetyQualificationEvidenceBundle(
            **_qualification_bundle_payload(
                "pi_hardware",
                future_claim="pi_runtime_observed",
            )
        )


def test_production_safety_qualification_bundle_cli_writes_receipts_and_cutover_audit(
    tmp_path,
) -> None:
    bundle_paths = []
    package_paths = []
    for index, area in enumerate(
        REQUIRED_PRODUCTION_SAFETY_QUALIFICATION_AREAS,
        start=1,
    ):
        bundle, package = _qualification_bundle_and_package_payload(
            tmp_path,
            area,
            index,
        )
        bundle_path = tmp_path / f"{area}-bundle.json"
        package_path = tmp_path / f"{area}-package.json"
        bundle_path.write_text(
            json.dumps(bundle),
            encoding="utf-8",
        )
        package_path.write_text(json.dumps(package), encoding="utf-8")
        bundle_paths.append(bundle_path)
        package_paths.append(package_path)
    source_integrity_dir = tmp_path / "source-integrity"
    admission_dir = tmp_path / "admissions"
    receipt_dir = tmp_path / "receipts"
    audit_path = tmp_path / "cutover-from-bundles.json"
    argv: list[str] = []
    for bundle_path, package_path in zip(bundle_paths, package_paths, strict=True):
        argv.extend(["--bundle", str(bundle_path)])
        argv.extend(["--source-package", str(package_path)])
    argv.extend(
        [
            "--source-root",
            str(tmp_path),
            "--source-integrity-output-dir",
            str(source_integrity_dir),
            "--admission-output-dir",
            str(admission_dir),
            "--receipt-output-dir",
            str(receipt_dir),
            "--output",
            str(audit_path),
            "--source-path",
            "prod://qualification/cutover/from-cli-bundles",
        ]
    )

    exit_code = main(argv)
    audit = load_production_safety_cutover_readiness_audit(audit_path)

    assert exit_code == 0
    assert audit.status == "ready_for_production_cutover"
    assert audit.ready_for_production_cutover is True
    assert len(list(source_integrity_dir.glob("*-source-integrity.json"))) == len(
        REQUIRED_PRODUCTION_SAFETY_QUALIFICATION_AREAS
    )
    assert len(list(admission_dir.glob("*-admission.json"))) == len(
        REQUIRED_PRODUCTION_SAFETY_QUALIFICATION_AREAS
    )
    assert len(list(receipt_dir.glob("*-receipt.json"))) == len(
        REQUIRED_PRODUCTION_SAFETY_QUALIFICATION_AREAS
    )


def test_production_safety_qualification_bundle_cli_keeps_cutover_blocked(
    tmp_path,
) -> None:
    bundle_paths = []
    package_paths = []
    for index, area in enumerate(
        REQUIRED_PRODUCTION_SAFETY_QUALIFICATION_AREAS,
        start=1,
    ):
        bundle, package = (
            _qualification_bundle_and_package_payload(
                tmp_path,
                area,
                index,
                omit_claim="provider_api_execution_observed",
            )
            if area == "live_provider_api"
            else _qualification_bundle_and_package_payload(tmp_path, area, index)
        )
        bundle_path = tmp_path / f"{area}-bundle.json"
        package_path = tmp_path / f"{area}-package.json"
        bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
        package_path.write_text(json.dumps(package), encoding="utf-8")
        bundle_paths.append(bundle_path)
        package_paths.append(package_path)
    audit_path = tmp_path / "blocked-cutover-from-bundles.json"
    argv: list[str] = []
    for bundle_path, package_path in zip(bundle_paths, package_paths, strict=True):
        argv.extend(["--bundle", str(bundle_path)])
        argv.extend(["--source-package", str(package_path)])
    argv.extend(["--source-root", str(tmp_path), "--output", str(audit_path)])

    exit_code = main(argv)
    audit = load_production_safety_cutover_readiness_audit(audit_path)

    assert exit_code == 0
    assert audit.status == "blocked_failed_required_qualification"
    assert audit.ready_for_production_cutover is False
    assert audit.failed_areas == ["live_provider_api"]


def test_production_safety_qualification_source_integrity_verifies_bundle_files(
    tmp_path,
) -> None:
    bundle, package = _qualification_bundle_and_package_payload(tmp_path)

    report = verify_production_safety_qualification_source_integrity(
        bundle,
        package,
        root_path=tmp_path,
        source_path="prod://qualification/live-provider-api/source-integrity",
    )
    output_path = tmp_path / "source-integrity-report.json"
    stored = write_production_safety_qualification_source_integrity_report(
        report,
        output_path,
    )
    loaded = load_production_safety_qualification_source_integrity_report(output_path)

    assert report.status == "source_integrity_verified"
    assert report.all_claim_sources_verified is True
    assert len(report.verified_evidence_refs) == len(bundle["claims"])
    assert report.missing_evidence_refs == []
    assert report.mismatched_evidence_refs == []
    assert report.unsafe_evidence_refs == []
    assert report.sensitive_evidence_refs == []
    assert all(row.source_integrity_verified for row in report.rows)
    assert stored == report
    assert loaded == report


def test_production_safety_qualification_source_integrity_blocks_bad_sources(
    tmp_path,
) -> None:
    bundle, package = _qualification_bundle_and_package_payload(tmp_path)
    missing_package = {
        **package,
        "artifacts": package["artifacts"][1:],
    }

    missing_report = verify_production_safety_qualification_source_integrity(
        bundle,
        missing_package,
        root_path=tmp_path,
    )

    assert missing_report.status == "blocked_source_integrity_failed"
    assert missing_report.all_claim_sources_verified is False
    assert missing_report.missing_evidence_refs == [
        bundle["claims"][0]["evidence_ref"]
    ]

    mismatched_package = {
        **package,
        "artifacts": [
            {
                **package["artifacts"][0],
                "evidence_sha256": "f" * 64,
            },
            *package["artifacts"][1:],
        ],
    }
    mismatched_report = verify_production_safety_qualification_source_integrity(
        bundle,
        mismatched_package,
        root_path=tmp_path,
    )

    assert mismatched_report.status == "blocked_source_integrity_failed"
    assert mismatched_report.mismatched_evidence_refs == [
        bundle["claims"][0]["evidence_ref"]
    ]

    unsafe_package = {
        **package,
        "artifacts": [
            {
                **package["artifacts"][0],
                "local_path": ".env",
            },
            *package["artifacts"][1:],
        ],
    }
    unsafe_report = verify_production_safety_qualification_source_integrity(
        bundle,
        unsafe_package,
        root_path=tmp_path,
    )

    assert unsafe_report.status == "blocked_source_integrity_failed"
    assert unsafe_report.unsafe_evidence_refs == [bundle["claims"][0]["evidence_ref"]]

    with pytest.raises(ValueError, match="source integrity package area must match"):
        verify_production_safety_qualification_source_integrity(
            bundle,
            {
                **package,
                "area": "pi_hardware",
            },
            root_path=tmp_path,
        )
    with pytest.raises(ValueError, match="cannot embed sensitive data"):
        ProductionSafetyQualificationEvidencePackage(
            **{
                **package,
                "credential_material_embedded": True,
            }
        )


def test_production_safety_qualification_threat_coverage_passes_complete_manifest(
    tmp_path,
) -> None:
    manifest, package = _threat_coverage_manifest_and_package_payload(tmp_path)
    source_report = (
        verify_production_safety_qualification_threat_coverage_source_integrity(
            manifest,
            package,
            root_path=tmp_path,
        )
    )

    audit = evaluate_production_safety_qualification_threat_coverage(
        manifest,
        source_integrity_report=source_report,
        source_path="prod://qualification/threat-coverage/audit",
    )
    output_path = tmp_path / "threat-coverage-audit.json"
    stored = write_production_safety_qualification_threat_coverage_audit(
        audit,
        output_path,
    )
    loaded = load_production_safety_qualification_threat_coverage_audit(output_path)

    assert audit.status == "qualification_threat_coverage_passed"
    assert audit.ready_for_production_cutover_threat_coverage is True
    assert audit.threat_model_covered is True
    assert audit.qualification_modes_covered is True
    assert audit.source_integrity_verified is True
    assert audit.source_integrity_report_sha256 == source_report.sha256
    assert audit.required_threats == list(REQUIRED_PRODUCTION_SAFETY_THREAT_COVERAGE)
    assert audit.required_qualification_modes == list(
        REQUIRED_PRODUCTION_SAFETY_QUALIFICATION_MODES
    )
    assert all(row.status == "covered" for row in audit.rows)
    assert stored == audit
    assert loaded == audit
    assert audit.external_call_performed_by_threat_audit is False
    assert audit.credential_material_loaded_by_threat_audit is False
    assert audit.safety_api_called_by_threat_audit is False
    assert audit.runtime_safety_truth_mutated_by_threat_audit is False


def test_production_safety_qualification_threat_coverage_source_integrity(
    tmp_path,
) -> None:
    manifest, package = _threat_coverage_manifest_and_package_payload(tmp_path)

    report = verify_production_safety_qualification_threat_coverage_source_integrity(
        manifest,
        package,
        root_path=tmp_path,
        source_path="prod://qualification/threat-coverage/source-integrity",
    )
    output_path = tmp_path / "threat-source-integrity-report.json"
    stored = write_production_safety_qualification_threat_coverage_source_integrity_report(
        report,
        output_path,
    )
    loaded = load_production_safety_qualification_threat_coverage_source_integrity_report(
        output_path
    )

    assert report.status == "source_integrity_verified"
    assert report.all_coverage_sources_verified is True
    assert len(report.verified_evidence_refs) == (
        len(REQUIRED_PRODUCTION_SAFETY_THREAT_COVERAGE)
        + len(REQUIRED_PRODUCTION_SAFETY_QUALIFICATION_MODES)
    )
    assert report.missing_evidence_refs == []
    assert report.mismatched_evidence_refs == []
    assert stored == report
    assert loaded == report


def test_production_safety_qualification_threat_coverage_blocks_unverified_sources(
    tmp_path,
) -> None:
    manifest, package = _threat_coverage_manifest_and_package_payload(tmp_path)
    missing_package = {
        **package,
        "artifacts": package["artifacts"][1:],
    }
    source_report = (
        verify_production_safety_qualification_threat_coverage_source_integrity(
            manifest,
            missing_package,
            root_path=tmp_path,
        )
    )

    no_source = evaluate_production_safety_qualification_threat_coverage(manifest)
    missing_source = evaluate_production_safety_qualification_threat_coverage(
        manifest,
        source_integrity_report=source_report,
    )

    assert no_source.status == "blocked_source_integrity_unverified"
    assert no_source.source_integrity_verified is False
    assert no_source.unverified_source_threats == list(
        REQUIRED_PRODUCTION_SAFETY_THREAT_COVERAGE
    )
    assert missing_source.status == "blocked_source_integrity_unverified"
    assert missing_source.unverified_source_threats == [
        REQUIRED_PRODUCTION_SAFETY_THREAT_COVERAGE[0]
    ]
    assert source_report.status == "blocked_source_integrity_failed"

    mismatched_package = {
        **package,
        "artifacts": [
            {
                **package["artifacts"][0],
                "evidence_sha256": "f" * 64,
            },
            *package["artifacts"][1:],
        ],
    }
    mismatch_report = (
        verify_production_safety_qualification_threat_coverage_source_integrity(
            manifest,
            mismatched_package,
            root_path=tmp_path,
        )
    )

    assert mismatch_report.status == "blocked_source_integrity_failed"
    assert mismatch_report.mismatched_evidence_refs == [
        manifest["threat_cases"][0]["evidence_ref"]
    ]


def test_production_safety_qualification_threat_coverage_blocks_gaps() -> None:
    missing = evaluate_production_safety_qualification_threat_coverage(
        _threat_coverage_manifest_payload(omit_threat="prompt_injection"),
    )
    failed = evaluate_production_safety_qualification_threat_coverage(
        _threat_coverage_manifest_payload(fail_mode="authority_boundary"),
    )
    stale = evaluate_production_safety_qualification_threat_coverage(
        _threat_coverage_manifest_payload(stale_threat="stale_candidates"),
    )

    assert missing.status == "blocked_missing_qualification_coverage"
    assert missing.ready_for_production_cutover_threat_coverage is False
    assert missing.missing_threats == ["prompt_injection"]
    assert failed.status == "blocked_failed_qualification_coverage"
    assert failed.failed_qualification_modes == ["authority_boundary"]
    assert stale.status == "blocked_stale_qualification_coverage"
    assert stale.stale_threats == ["stale_candidates"]

    with pytest.raises(ValueError, match="cannot perform effects"):
        ProductionSafetyQualificationThreatCoverageManifest(
            **{
                **_threat_coverage_manifest_payload(),
                "external_call_performed_by_threat_audit": True,
            }
        )


def test_production_safety_qualification_threat_coverage_cli_writes_audit(
    tmp_path,
) -> None:
    manifest, package = _threat_coverage_manifest_and_package_payload(tmp_path)
    manifest_path = tmp_path / "threat-coverage-manifest.json"
    package_path = tmp_path / "threat-coverage-package.json"
    manifest_path.write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
    package_path.write_text(
        json.dumps(package),
        encoding="utf-8",
    )
    output_path = tmp_path / "threat-coverage-audit.json"
    source_integrity_dir = tmp_path / "threat-source-integrity"

    exit_code = main(
        [
            "--threat-coverage",
            str(manifest_path),
            "--threat-coverage-source-package",
            str(package_path),
            "--source-root",
            str(tmp_path),
            "--source-integrity-output-dir",
            str(source_integrity_dir),
            "--threat-coverage-output",
            str(output_path),
            "--source-path",
            "prod://qualification/threat-coverage/from-cli",
        ]
    )
    loaded = load_production_safety_qualification_threat_coverage_audit(output_path)

    assert exit_code == 0
    assert loaded.status == "qualification_threat_coverage_passed"
    assert loaded.ready_for_production_cutover_threat_coverage is True
    assert (
        source_integrity_dir / "00-threat-coverage-source-integrity.json"
    ).exists()


def test_production_safety_qualification_dossier_cli_writes_ready_report(
    tmp_path,
) -> None:
    manifest_path = tmp_path / "dossier-manifest.json"
    manifest_path.write_text(
        json.dumps(_dossier_manifest_payload(tmp_path)),
        encoding="utf-8",
    )
    report_path = tmp_path / "dossier-report.json"
    cutover_path = tmp_path / "dossier-cutover-audit.json"
    threat_coverage_path = tmp_path / "dossier-threat-coverage-audit.json"
    source_integrity_dir = tmp_path / "dossier-source-integrity"
    admission_dir = tmp_path / "dossier-admissions"
    receipt_dir = tmp_path / "dossier-receipts"

    exit_code = main(
        [
            "--dossier",
            str(manifest_path),
            "--dossier-output",
            str(report_path),
            "--output",
            str(cutover_path),
            "--threat-coverage-output",
            str(threat_coverage_path),
            "--source-integrity-output-dir",
            str(source_integrity_dir),
            "--admission-output-dir",
            str(admission_dir),
            "--receipt-output-dir",
            str(receipt_dir),
            "--source-path",
            "prod://qualification/dossier/report",
        ]
    )
    report = load_production_safety_qualification_dossier_report(report_path)
    cutover = load_production_safety_cutover_readiness_audit(cutover_path)
    threat_coverage = load_production_safety_qualification_threat_coverage_audit(
        threat_coverage_path
    )

    assert exit_code == 0
    assert report.status == "dossier_ready_for_production_cutover"
    assert report.ready_for_production_cutover is True
    assert report.threat_coverage_ready is True
    assert report.threat_coverage_status == "qualification_threat_coverage_passed"
    assert report.missing_areas == []
    assert report.failed_areas == []
    assert report.cutover_audit.ready_for_production_cutover is True
    assert report.threat_coverage_audit == threat_coverage
    assert cutover.ready_for_production_cutover is True
    assert threat_coverage.ready_for_production_cutover_threat_coverage is True
    assert all(row.status == "qualified" for row in report.rows)
    assert len(list(source_integrity_dir.glob("*-source-integrity.json"))) == (
        len(REQUIRED_PRODUCTION_SAFETY_QUALIFICATION_AREAS) + 1
    )
    assert len(list(admission_dir.glob("*-admission.json"))) == len(
        REQUIRED_PRODUCTION_SAFETY_QUALIFICATION_AREAS
    )
    assert len(list(receipt_dir.glob("*-receipt.json"))) == len(
        REQUIRED_PRODUCTION_SAFETY_QUALIFICATION_AREAS
    )


def test_production_safety_qualification_dossier_blocks_missing_and_failed_entries(
    tmp_path,
) -> None:
    missing_report = run_production_safety_qualification_dossier(
        _dossier_manifest_payload(tmp_path, omit_area="pi_hardware"),
    )

    assert missing_report.status == "blocked_dossier_incomplete"
    assert missing_report.ready_for_production_cutover is False
    assert missing_report.missing_areas == ["pi_hardware"]
    assert missing_report.cutover_audit.status == "blocked_missing_required_qualification"

    failed_report = run_production_safety_qualification_dossier(
        _dossier_manifest_payload(
            tmp_path,
            mutate_package_area="live_provider_api",
        ),
    )

    assert failed_report.status == "blocked_dossier_failed"
    assert failed_report.ready_for_production_cutover is False
    assert failed_report.failed_areas == ["live_provider_api"]
    assert failed_report.rows[0].status == "source_integrity_failed"
    assert failed_report.cutover_audit.status == "blocked_failed_required_qualification"

    output_path = tmp_path / "failed-dossier-report.json"
    stored = write_production_safety_qualification_dossier_report(
        failed_report,
        output_path,
    )

    assert stored == failed_report


def test_production_safety_qualification_dossier_requires_threat_coverage(
    tmp_path,
) -> None:
    missing_threat_report = run_production_safety_qualification_dossier(
        _dossier_manifest_payload(tmp_path, omit_threat_coverage=True),
    )
    failed_threat_report = run_production_safety_qualification_dossier(
        _dossier_manifest_payload(tmp_path, fail_threat="authority_escalation"),
    )

    assert missing_threat_report.status == "blocked_dossier_incomplete"
    assert missing_threat_report.ready_for_production_cutover is False
    assert missing_threat_report.threat_coverage_audit is None
    assert missing_threat_report.threat_coverage_status == "missing"
    assert "threat_coverage_manifest_missing" in missing_threat_report.dossier_blockers
    assert missing_threat_report.cutover_audit.ready_for_production_cutover is True

    assert failed_threat_report.status == "blocked_dossier_failed"
    assert failed_threat_report.ready_for_production_cutover is False
    assert failed_threat_report.threat_coverage_ready is False
    assert (
        failed_threat_report.threat_coverage_status
        == "blocked_failed_qualification_coverage"
    )
    assert failed_threat_report.threat_coverage_audit is not None
    assert failed_threat_report.threat_coverage_audit.failed_threats == [
        "authority_escalation"
    ]


def test_production_safety_qualification_gap_plan_resolves_ready_dossier(
    tmp_path,
) -> None:
    report = run_production_safety_qualification_dossier(
        _dossier_manifest_payload(tmp_path),
    )

    plan = evaluate_production_safety_qualification_gap_plan(
        report,
        source_path="prod://qualification/gap-plan/ready",
    )
    output_path = tmp_path / "gap-plan-ready.json"
    stored = write_production_safety_qualification_gap_plan(plan, output_path)
    loaded = load_production_safety_qualification_gap_plan(output_path)

    assert report.ready_for_production_cutover is True
    assert plan.status == "production_qualification_gaps_resolved"
    assert plan.ready_for_production_cutover is True
    assert plan.open_gap_count == 0
    assert plan.rows == []
    assert plan.external_call_performed_by_gap_plan is False
    assert plan.safety_api_called_by_gap_plan is False
    assert plan.runtime_safety_truth_mutated_by_gap_plan is False
    assert stored == plan
    assert loaded == plan


def test_production_safety_qualification_gap_plan_lists_area_and_threat_gaps(
    tmp_path,
) -> None:
    missing_area_report = run_production_safety_qualification_dossier(
        _dossier_manifest_payload(tmp_path, omit_area="pi_hardware"),
    )
    missing_threat_source_manifest = _dossier_manifest_payload(tmp_path)
    del missing_threat_source_manifest["threat_coverage_source_package_path"]
    missing_threat_source_report = run_production_safety_qualification_dossier(
        missing_threat_source_manifest,
    )

    area_plan = evaluate_production_safety_qualification_gap_plan(
        missing_area_report
    )
    threat_plan = evaluate_production_safety_qualification_gap_plan(
        missing_threat_source_report
    )

    assert area_plan.status == "blocked_production_qualification_gaps_open"
    assert area_plan.ready_for_production_cutover is False
    assert area_plan.open_gap_count == 1
    assert area_plan.rows[0].gap_kind == "area_qualification"
    assert area_plan.rows[0].area == "pi_hardware"
    assert area_plan.rows[0].action == "provide_area_bundle_and_source_package"

    assert threat_plan.status == "blocked_production_qualification_gaps_open"
    assert threat_plan.ready_for_production_cutover is False
    assert any(row.gap_kind == "threat_source_integrity" for row in threat_plan.rows)
    assert any(
        row.gap_kind == "threat_coverage"
        and row.threat_id == "hallucination"
        and row.action == "repair_threat_coverage_source_integrity"
        for row in threat_plan.rows
    )
    assert any(
        row.gap_kind == "qualification_mode_coverage"
        and row.mode_id == "authority_boundary"
        and row.action == "repair_threat_coverage_source_integrity"
        for row in threat_plan.rows
    )


def test_production_safety_qualification_gap_plan_cli_writes_artifact(
    tmp_path,
) -> None:
    report = run_production_safety_qualification_dossier(
        _dossier_manifest_payload(tmp_path, omit_area="live_provider_api"),
    )
    report_path = tmp_path / "blocked-dossier-report.json"
    plan_path = tmp_path / "gap-plan.json"
    write_production_safety_qualification_dossier_report(report, report_path)

    exit_code = main(
        [
            "--gap-plan",
            str(report_path),
            "--gap-plan-output",
            str(plan_path),
            "--source-path",
            "prod://qualification/gap-plan/from-cli",
        ]
    )
    loaded = load_production_safety_qualification_gap_plan(plan_path)

    assert exit_code == 0
    assert loaded.status == "blocked_production_qualification_gaps_open"
    assert loaded.open_gap_count == 1
    assert loaded.rows[0].area == "live_provider_api"


def test_production_safety_qualification_evidence_request_pack_resolves_ready_plan(
    tmp_path,
) -> None:
    report = run_production_safety_qualification_dossier(
        _dossier_manifest_payload(tmp_path),
    )
    plan = evaluate_production_safety_qualification_gap_plan(report)

    pack = build_production_safety_qualification_evidence_request_pack(plan)
    output_path = tmp_path / "evidence-request-pack-ready.json"
    stored = write_production_safety_qualification_evidence_request_pack(
        pack,
        output_path,
    )
    loaded = load_production_safety_qualification_evidence_request_pack(output_path)

    assert plan.status == "production_qualification_gaps_resolved"
    assert pack.status == "no_evidence_requests_required"
    assert pack.request_count == 0
    assert pack.rows == []
    assert pack.external_call_performed_by_request_pack is False
    assert pack.credential_material_loaded_by_request_pack is False
    assert pack.runtime_safety_truth_mutated_by_request_pack is False
    assert stored == pack
    assert loaded == pack


def test_production_safety_qualification_evidence_request_pack_lists_requests(
    tmp_path,
) -> None:
    report = run_production_safety_qualification_dossier(
        _dossier_manifest_payload(tmp_path, omit_area="pi_hardware"),
    )
    plan = evaluate_production_safety_qualification_gap_plan(report)

    pack = build_production_safety_qualification_evidence_request_pack(
        plan,
        source_path="prod://qualification/evidence-requests/pi-hardware",
    )

    assert pack.status == "evidence_request_pack_ready"
    assert pack.request_count == 2
    assert {row.request_kind for row in pack.rows} == {
        "area_evidence_bundle",
        "area_source_package",
    }
    assert all(row.area == "pi_hardware" for row in pack.rows)
    assert pack.rows[0].required_claims == list(
        PRODUCTION_SAFETY_QUALIFICATION_REQUIRED_CLAIMS["pi_hardware"]
    )
    assert all(row.source_integrity_required for row in pack.rows)
    assert all(row.human_review_required for row in pack.rows)
    assert all(row.external_effects_prohibited for row in pack.rows)


def test_production_safety_qualification_evidence_request_pack_cli_writes_artifact(
    tmp_path,
) -> None:
    missing_threat_source_manifest = _dossier_manifest_payload(tmp_path)
    del missing_threat_source_manifest["threat_coverage_source_package_path"]
    report = run_production_safety_qualification_dossier(
        missing_threat_source_manifest,
    )
    plan = evaluate_production_safety_qualification_gap_plan(report)
    plan_path = tmp_path / "gap-plan.json"
    request_path = tmp_path / "evidence-request-pack.json"
    write_production_safety_qualification_gap_plan(plan, plan_path)

    exit_code = main(
        [
            "--evidence-request-pack",
            str(plan_path),
            "--evidence-request-output",
            str(request_path),
            "--source-path",
            "prod://qualification/evidence-requests/from-cli",
        ]
    )
    loaded = load_production_safety_qualification_evidence_request_pack(request_path)

    assert exit_code == 0
    assert loaded.status == "evidence_request_pack_ready"
    assert loaded.request_count > 1
    assert any(
        row.request_kind == "threat_coverage_source_package"
        for row in loaded.rows
    )
    assert any(
        row.request_kind == "threat_coverage_case"
        and row.threat_id == "hallucination"
        for row in loaded.rows
    )


def test_production_safety_qualification_evidence_fulfillment_verifies_requests(
    tmp_path,
) -> None:
    report = run_production_safety_qualification_dossier(
        _dossier_manifest_payload(tmp_path, omit_area="pi_hardware"),
    )
    plan = evaluate_production_safety_qualification_gap_plan(report)
    pack = build_production_safety_qualification_evidence_request_pack(plan)
    manifest, source_package = _fulfillment_manifest_and_source_package_payload(
        tmp_path,
        pack,
    )
    source_report = (
        verify_production_safety_qualification_evidence_fulfillment_source_integrity(
            manifest,
            source_package,
            root_path=tmp_path,
        )
    )
    source_output_path = tmp_path / "evidence-fulfillment-source-integrity.json"
    stored_source_report = (
        write_production_safety_qualification_evidence_fulfillment_source_integrity_report(
            source_report,
            source_output_path,
        )
    )
    loaded_source_report = (
        load_production_safety_qualification_evidence_fulfillment_source_integrity_report(
            source_output_path
        )
    )

    fulfillment = evaluate_production_safety_qualification_evidence_fulfillment(
        pack,
        manifest,
        source_integrity_report=source_report,
        source_path="prod://qualification/evidence-fulfillment/report",
    )
    output_path = tmp_path / "evidence-fulfillment-report.json"
    stored = write_production_safety_qualification_evidence_fulfillment_report(
        fulfillment,
        output_path,
    )
    loaded = load_production_safety_qualification_evidence_fulfillment_report(
        output_path
    )

    assert pack.status == "evidence_request_pack_ready"
    assert source_report.status == "fulfillment_source_integrity_verified"
    assert stored_source_report == source_report
    assert loaded_source_report == source_report
    assert fulfillment.status == "evidence_request_fulfillment_verified"
    assert fulfillment.all_requested_evidence_fulfilled is True
    assert fulfillment.source_integrity_verified is True
    assert fulfillment.source_integrity_report_sha256 == source_report.sha256
    assert fulfillment.fulfilled_request_count == pack.request_count
    assert fulfillment.missing_request_count == 0
    assert fulfillment.mismatched_request_count == 0
    assert fulfillment.rejected_request_count == 0
    assert all(row.fulfilled for row in fulfillment.rows)
    assert fulfillment.external_call_performed_by_fulfillment is False
    assert fulfillment.safety_api_called_by_fulfillment is False
    assert fulfillment.runtime_safety_truth_mutated_by_fulfillment is False
    assert stored == fulfillment
    assert loaded == fulfillment


def test_production_safety_qualification_evidence_fulfillment_blocks_bad_returns(
    tmp_path,
) -> None:
    report = run_production_safety_qualification_dossier(
        _dossier_manifest_payload(tmp_path, omit_area="transport_client"),
    )
    plan = evaluate_production_safety_qualification_gap_plan(report)
    pack = build_production_safety_qualification_evidence_request_pack(plan)
    first_key = _evidence_request_row_key(pack.rows[0])
    missing_manifest, missing_package = _fulfillment_manifest_and_source_package_payload(
        tmp_path,
        pack,
        omit_key=first_key,
    )
    mismatched_manifest, mismatched_package = (
        _fulfillment_manifest_and_source_package_payload(
            tmp_path,
            pack,
            wrong_kind_key=first_key,
        )
    )
    rejected_manifest, rejected_package = (
        _fulfillment_manifest_and_source_package_payload(
            tmp_path,
            pack,
            reject_key=first_key,
        )
    )
    missing_review_manifest, missing_review_package = (
        _fulfillment_manifest_and_source_package_payload(
            tmp_path,
            pack,
            missing_review_key=first_key,
        )
    )

    missing = evaluate_production_safety_qualification_evidence_fulfillment(
        pack,
        missing_manifest,
        source_integrity_report=(
            verify_production_safety_qualification_evidence_fulfillment_source_integrity(
                missing_manifest,
                missing_package,
                root_path=tmp_path,
            )
        ),
    )
    mismatched = evaluate_production_safety_qualification_evidence_fulfillment(
        pack,
        mismatched_manifest,
        source_integrity_report=(
            verify_production_safety_qualification_evidence_fulfillment_source_integrity(
                mismatched_manifest,
                mismatched_package,
                root_path=tmp_path,
            )
        ),
    )
    rejected = evaluate_production_safety_qualification_evidence_fulfillment(
        pack,
        rejected_manifest,
        source_integrity_report=(
            verify_production_safety_qualification_evidence_fulfillment_source_integrity(
                rejected_manifest,
                rejected_package,
                root_path=tmp_path,
            )
        ),
    )
    missing_review = evaluate_production_safety_qualification_evidence_fulfillment(
        pack,
        missing_review_manifest,
        source_integrity_report=(
            verify_production_safety_qualification_evidence_fulfillment_source_integrity(
                missing_review_manifest,
                missing_review_package,
                root_path=tmp_path,
            )
        ),
    )

    assert missing.status == "blocked_missing_requested_evidence"
    assert missing.rows[0].status == "missing"
    assert "requested_evidence_submission_missing" in missing.rows[0].blockers

    assert mismatched.status == "blocked_mismatched_requested_evidence"
    assert mismatched.rows[0].status == "mismatched"
    assert "submitted_artifact_kind_not_requested" in mismatched.rows[0].blockers

    assert rejected.status == "blocked_rejected_requested_evidence"
    assert rejected.rows[0].status == "rejected"
    assert "requested_evidence_submission_rejected" in rejected.rows[0].blockers

    assert missing_review.status == "blocked_mismatched_requested_evidence"
    assert missing_review.rows[0].status == "mismatched"
    assert (
        "requested_evidence_human_review_missing"
        in missing_review.rows[0].blockers
    )

    with pytest.raises(ValueError, match="cannot perform effects"):
        ProductionSafetyQualificationEvidenceFulfillmentManifest(
            **{
                **_fulfillment_manifest_payload(pack),
                "external_call_performed_by_fulfillment": True,
            }
        )


def test_production_safety_qualification_evidence_fulfillment_requires_source_integrity(
    tmp_path,
) -> None:
    report = run_production_safety_qualification_dossier(
        _dossier_manifest_payload(tmp_path, omit_area="credential_access_path"),
    )
    plan = evaluate_production_safety_qualification_gap_plan(report)
    pack = build_production_safety_qualification_evidence_request_pack(plan)
    manifest, package = _fulfillment_manifest_and_source_package_payload(
        tmp_path,
        pack,
    )

    no_source = evaluate_production_safety_qualification_evidence_fulfillment(
        pack,
        manifest,
    )
    assert no_source.status == "blocked_fulfillment_source_integrity_unverified"
    assert no_source.source_integrity_verified is False
    assert no_source.source_unverified_request_count == pack.request_count
    assert all(row.status == "source_unverified" for row in no_source.rows)

    missing_package = {
        **package,
        "artifacts": package["artifacts"][1:],
    }
    missing_source = (
        verify_production_safety_qualification_evidence_fulfillment_source_integrity(
            manifest,
            missing_package,
            root_path=tmp_path,
        )
    )
    blocked = evaluate_production_safety_qualification_evidence_fulfillment(
        pack,
        manifest,
        source_integrity_report=missing_source,
    )
    assert missing_source.status == "blocked_fulfillment_source_integrity_failed"
    assert missing_source.missing_submitted_artifact_refs == [
        manifest["submissions"][0]["submitted_artifact_ref"]
    ]
    assert blocked.status == "blocked_fulfillment_source_integrity_unverified"
    assert blocked.unverified_source_refs == [
        manifest["submissions"][0]["submitted_artifact_ref"]
    ]

    bad_hash_package = {
        **package,
        "artifacts": [
            {
                **package["artifacts"][0],
                "submitted_artifact_sha256": "f" * 64,
            },
            *package["artifacts"][1:],
        ],
    }
    bad_hash = (
        verify_production_safety_qualification_evidence_fulfillment_source_integrity(
            manifest,
            bad_hash_package,
            root_path=tmp_path,
        )
    )
    assert bad_hash.mismatched_submitted_artifact_refs == [
        manifest["submissions"][0]["submitted_artifact_ref"]
    ]

    unsafe_package = {
        **package,
        "artifacts": [
            {
                **package["artifacts"][0],
                "local_path": ".env",
            },
            *package["artifacts"][1:],
        ],
    }
    unsafe = (
        verify_production_safety_qualification_evidence_fulfillment_source_integrity(
            manifest,
            unsafe_package,
            root_path=tmp_path,
        )
    )
    assert unsafe.unsafe_submitted_artifact_refs == [
        manifest["submissions"][0]["submitted_artifact_ref"]
    ]

    sensitive_package = {
        **package,
        "artifacts": [
            {
                **package["artifacts"][0],
                "raw_payload_present": True,
            },
            *package["artifacts"][1:],
        ],
    }
    sensitive = (
        verify_production_safety_qualification_evidence_fulfillment_source_integrity(
            manifest,
            sensitive_package,
            root_path=tmp_path,
        )
    )
    assert sensitive.sensitive_submitted_artifact_refs == [
        manifest["submissions"][0]["submitted_artifact_ref"]
    ]

    with pytest.raises(ValueError, match="cannot perform effects"):
        ProductionSafetyQualificationEvidenceFulfillmentSourcePackage(
            **{
                **package,
                "external_call_performed_by_source_package": True,
            }
        )


def test_production_safety_qualification_evidence_fulfillment_cli_writes_report(
    tmp_path,
) -> None:
    report = run_production_safety_qualification_dossier(
        _dossier_manifest_payload(tmp_path, omit_area="outbound_delivery"),
    )
    plan = evaluate_production_safety_qualification_gap_plan(report)
    pack = build_production_safety_qualification_evidence_request_pack(
        plan,
        source_path="prod://qualification/evidence-requests/from-cli-pack",
    )
    pack_path = tmp_path / "evidence-request-pack.json"
    manifest_path = tmp_path / "evidence-fulfillment-manifest.json"
    source_package_path = tmp_path / "evidence-fulfillment-source-package.json"
    source_integrity_path = tmp_path / "evidence-fulfillment-source-integrity.json"
    output_path = tmp_path / "evidence-fulfillment-report.json"
    manifest, source_package = _fulfillment_manifest_and_source_package_payload(
        tmp_path,
        pack,
    )
    write_production_safety_qualification_evidence_request_pack(pack, pack_path)
    manifest_path.write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
    source_package_path.write_text(
        json.dumps(source_package),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "--evidence-fulfillment-request-pack",
            str(pack_path),
            "--evidence-fulfillment-manifest",
            str(manifest_path),
            "--evidence-fulfillment-source-package",
            str(source_package_path),
            "--evidence-fulfillment-source-integrity-output",
            str(source_integrity_path),
            "--source-root",
            str(tmp_path),
            "--evidence-fulfillment-output",
            str(output_path),
            "--source-path",
            "prod://qualification/evidence-fulfillment/from-cli",
        ]
    )
    loaded = load_production_safety_qualification_evidence_fulfillment_report(
        output_path
    )
    source_integrity = (
        load_production_safety_qualification_evidence_fulfillment_source_integrity_report(
            source_integrity_path
        )
    )

    assert exit_code == 0
    assert source_integrity.status == "fulfillment_source_integrity_verified"
    assert loaded.status == "evidence_request_fulfillment_verified"
    assert loaded.all_requested_evidence_fulfilled is True
    assert loaded.source_integrity_report_sha256 == source_integrity.sha256
    assert loaded.fulfilled_request_count == pack.request_count


def test_production_safety_qualification_remediation_readiness_allows_dossier_rerun(
    tmp_path,
) -> None:
    report = run_production_safety_qualification_dossier(
        _dossier_manifest_payload(tmp_path, omit_area="pi_hardware"),
    )
    plan = evaluate_production_safety_qualification_gap_plan(report)
    pack = build_production_safety_qualification_evidence_request_pack(plan)
    _manifest, _source_package, _source_report, fulfillment = (
        _source_verified_fulfillment_report(tmp_path, pack)
    )

    remediation = evaluate_production_safety_qualification_remediation_readiness(
        plan,
        pack,
        fulfillment,
        source_path="prod://qualification/remediation/pi-hardware",
    )
    output_path = tmp_path / "remediation-readiness.json"
    stored = write_production_safety_qualification_remediation_readiness_report(
        remediation,
        output_path,
    )
    loaded = load_production_safety_qualification_remediation_readiness_report(
        output_path
    )

    assert remediation.status == "ready_for_dossier_rerun"
    assert remediation.ready_for_dossier_rerun is True
    assert remediation.ready_for_production_cutover is False
    assert remediation.all_open_gaps_remediated is True
    assert remediation.ready_gap_count == 1
    assert remediation.blocked_gap_count == 0
    assert remediation.rows[0].gap_kind == "area_qualification"
    assert remediation.rows[0].area == "pi_hardware"
    assert remediation.rows[0].expected_request_count == 2
    assert remediation.rows[0].fulfilled_request_count == 2
    assert remediation.external_call_performed_by_remediation is False
    assert remediation.safety_api_called_by_remediation is False
    assert remediation.runtime_safety_truth_mutated_by_remediation is False
    assert stored == remediation
    assert loaded == remediation


def test_production_safety_qualification_remediation_readiness_blocks_incomplete_links(
    tmp_path,
) -> None:
    report = run_production_safety_qualification_dossier(
        _dossier_manifest_payload(tmp_path, omit_area="transport_client"),
    )
    plan = evaluate_production_safety_qualification_gap_plan(report)
    pack = build_production_safety_qualification_evidence_request_pack(plan)
    manifest, _source_package = _fulfillment_manifest_and_source_package_payload(
        tmp_path,
        pack,
    )
    source_unverified = evaluate_production_safety_qualification_evidence_fulfillment(
        pack,
        manifest,
    )

    blocked = evaluate_production_safety_qualification_remediation_readiness(
        plan,
        pack,
        source_unverified,
    )
    assert blocked.status == "blocked_remediation_incomplete"
    assert blocked.ready_for_dossier_rerun is False
    assert blocked.all_open_gaps_remediated is False
    assert blocked.rows[0].status == "blocked_fulfillment_source_integrity_unverified"
    assert any(
        "requested_evidence_source_integrity_unverified" in blocker
        for blocker in blocked.rows[0].blockers
    )

    partial_pack_payload = {
        **pack.model_dump(mode="json"),
        "request_count": pack.request_count - 1,
        "rows": pack.model_dump(mode="json")["rows"][1:],
    }
    partial_pack = build_production_safety_qualification_evidence_request_pack(
        plan
    ).model_validate(partial_pack_payload)
    partial_fulfillment = evaluate_production_safety_qualification_evidence_fulfillment(
        partial_pack,
        _fulfillment_manifest_payload(partial_pack),
    )
    mismatch = evaluate_production_safety_qualification_remediation_readiness(
        plan,
        partial_pack,
        partial_fulfillment,
    )
    assert mismatch.status == "blocked_remediation_incomplete"
    assert mismatch.rows[0].status == "blocked_request_pack_mismatch"
    assert any(
        blocker.startswith("request_pack_row_missing:")
        for blocker in mismatch.rows[0].blockers
    )

    with pytest.raises(ValueError, match="cannot claim production cutover"):
        ProductionSafetyQualificationRemediationReadinessReport(
            **{
                **blocked.model_dump(mode="json"),
                "ready_for_production_cutover": True,
            }
        )


def test_production_safety_qualification_remediation_readiness_cli_writes_report(
    tmp_path,
) -> None:
    report = run_production_safety_qualification_dossier(
        _dossier_manifest_payload(tmp_path, omit_area="resident_freshness_attestor"),
    )
    plan = evaluate_production_safety_qualification_gap_plan(
        report,
        source_path="prod://qualification/gap-plan/remediation-cli",
    )
    pack = build_production_safety_qualification_evidence_request_pack(
        plan,
        source_path="prod://qualification/evidence-requests/remediation-cli",
    )
    _manifest, _source_package, _source_report, fulfillment = (
        _source_verified_fulfillment_report(tmp_path, pack)
    )
    plan_path = tmp_path / "gap-plan.json"
    pack_path = tmp_path / "request-pack.json"
    fulfillment_path = tmp_path / "fulfillment-report.json"
    output_path = tmp_path / "remediation-readiness.json"
    write_production_safety_qualification_gap_plan(plan, plan_path)
    write_production_safety_qualification_evidence_request_pack(pack, pack_path)
    write_production_safety_qualification_evidence_fulfillment_report(
        fulfillment,
        fulfillment_path,
    )

    exit_code = main(
        [
            "--remediation-gap-plan",
            str(plan_path),
            "--remediation-request-pack",
            str(pack_path),
            "--remediation-fulfillment-report",
            str(fulfillment_path),
            "--remediation-output",
            str(output_path),
            "--source-path",
            "prod://qualification/remediation/from-cli",
        ]
    )
    loaded = load_production_safety_qualification_remediation_readiness_report(
        output_path
    )

    assert exit_code == 0
    assert loaded.status == "ready_for_dossier_rerun"
    assert loaded.ready_for_dossier_rerun is True
    assert loaded.ready_for_production_cutover is False


def test_production_safety_qualification_external_action_packet_requires_operator_authorization(
    tmp_path,
) -> None:
    report = run_production_safety_qualification_dossier(
        _dossier_manifest_payload(tmp_path, omit_area="pi_hardware"),
    )
    plan = evaluate_production_safety_qualification_gap_plan(report)
    pack = build_production_safety_qualification_evidence_request_pack(plan)
    _manifest, _source_package, _source_report, fulfillment = (
        _source_verified_fulfillment_report(tmp_path, pack)
    )
    remediation = evaluate_production_safety_qualification_remediation_readiness(
        plan,
        pack,
        fulfillment,
    )

    packet = build_production_safety_qualification_external_action_packet(
        remediation,
        source_path="prod://qualification/external-actions/pi-hardware",
    )
    output_path = tmp_path / "external-action-packet.json"
    stored = write_production_safety_qualification_external_action_packet(
        packet,
        output_path,
    )
    loaded = load_production_safety_qualification_external_action_packet(output_path)

    assert packet.status == "external_actions_ready_for_operator_authorization"
    assert packet.ready_for_operator_authorization is True
    assert packet.ready_for_production_cutover is False
    assert packet.execution_allowed is False
    assert packet.ready_action_count == 1
    assert packet.blocked_action_count == 0
    assert packet.remediation_report_sha256 == remediation.sha256
    assert packet.rows[0].area == "pi_hardware"
    assert packet.rows[0].external_action_kind == "pi_hardware_validation"
    assert packet.rows[0].status == "ready_for_operator_authorization"
    assert packet.rows[0].ready_for_operator_authorization is True
    assert packet.rows[0].dossier_rerun_required is True
    assert packet.rows[0].requires_explicit_operator_approval is True
    assert packet.rows[0].reviewed_effect_boundary_required is True
    assert packet.rows[0].execution_allowed is False
    assert "production_qualification_receipt" in packet.rows[0].required_artifacts
    assert packet.external_call_performed_by_packet is False
    assert packet.safety_api_called_by_packet is False
    assert packet.runtime_safety_truth_mutated_by_packet is False
    assert stored == packet
    assert loaded == packet

    with pytest.raises(ValueError, match="Input should be False"):
        ProductionSafetyQualificationExternalActionPacket(
            **{
                **packet.model_dump(mode="json"),
                "execution_allowed": True,
            }
        )


def test_production_safety_qualification_external_action_packet_blocks_incomplete_remediation(
    tmp_path,
) -> None:
    report = run_production_safety_qualification_dossier(
        _dossier_manifest_payload(tmp_path, omit_area="transport_client"),
    )
    plan = evaluate_production_safety_qualification_gap_plan(report)
    pack = build_production_safety_qualification_evidence_request_pack(plan)
    manifest, _source_package = _fulfillment_manifest_and_source_package_payload(
        tmp_path,
        pack,
    )
    source_unverified = evaluate_production_safety_qualification_evidence_fulfillment(
        pack,
        manifest,
    )
    remediation = evaluate_production_safety_qualification_remediation_readiness(
        plan,
        pack,
        source_unverified,
    )

    packet = build_production_safety_qualification_external_action_packet(
        remediation,
    )

    assert packet.status == "blocked_external_actions_incomplete"
    assert packet.ready_for_operator_authorization is False
    assert packet.ready_action_count == 0
    assert packet.blocked_action_count == 1
    assert packet.rows[0].area == "transport_client"
    assert packet.rows[0].external_action_kind == "transport_client_qualification"
    assert packet.rows[0].status == "blocked_remediation_incomplete"
    assert packet.rows[0].ready_for_operator_authorization is False
    assert packet.rows[0].dossier_rerun_required is False
    assert any(
        "requested_evidence_source_integrity_unverified" in blocker
        for blocker in packet.rows[0].blockers
    )


def test_production_safety_qualification_external_action_packet_cli_writes_packet(
    tmp_path,
) -> None:
    report = run_production_safety_qualification_dossier(
        _dossier_manifest_payload(tmp_path, omit_area="outbound_delivery"),
    )
    plan = evaluate_production_safety_qualification_gap_plan(report)
    pack = build_production_safety_qualification_evidence_request_pack(plan)
    _manifest, _source_package, _source_report, fulfillment = (
        _source_verified_fulfillment_report(tmp_path, pack)
    )
    remediation = evaluate_production_safety_qualification_remediation_readiness(
        plan,
        pack,
        fulfillment,
        source_path="prod://qualification/remediation/external-action-cli",
    )
    remediation_path = tmp_path / "remediation-readiness.json"
    output_path = tmp_path / "external-action-packet.json"
    write_production_safety_qualification_remediation_readiness_report(
        remediation,
        remediation_path,
    )

    exit_code = main(
        [
            "--external-action-remediation",
            str(remediation_path),
            "--external-action-output",
            str(output_path),
            "--source-path",
            "prod://qualification/external-actions/from-cli",
        ]
    )
    loaded = load_production_safety_qualification_external_action_packet(output_path)

    assert exit_code == 0
    assert loaded.status == "external_actions_ready_for_operator_authorization"
    assert loaded.rows[0].area == "outbound_delivery"
    assert loaded.rows[0].external_action_kind == "delivery_verification"
    assert loaded.ready_for_operator_authorization is True
    assert loaded.execution_allowed is False


def test_production_safety_qualification_external_authorization_records_review_without_execution(
    tmp_path,
) -> None:
    report = run_production_safety_qualification_dossier(
        _dossier_manifest_payload(tmp_path, omit_area="pi_hardware"),
    )
    plan = evaluate_production_safety_qualification_gap_plan(report)
    pack = build_production_safety_qualification_evidence_request_pack(plan)
    _manifest, _source_package, _source_report, fulfillment = (
        _source_verified_fulfillment_report(tmp_path, pack)
    )
    remediation = evaluate_production_safety_qualification_remediation_readiness(
        plan,
        pack,
        fulfillment,
    )
    packet = build_production_safety_qualification_external_action_packet(
        remediation,
        source_path="prod://qualification/external-actions/pi-hardware",
    )
    authorization_manifest = _external_authorization_manifest_payload(packet)

    authorization = evaluate_production_safety_qualification_external_authorization(
        packet,
        authorization_manifest,
        source_path="prod://qualification/external-authorization/pi-hardware",
    )
    output_path = tmp_path / "external-authorization-report.json"
    stored = write_production_safety_qualification_external_authorization_report(
        authorization,
        output_path,
    )
    loaded = load_production_safety_qualification_external_authorization_report(
        output_path
    )

    assert authorization.status == "external_authorization_recorded"
    assert authorization.all_authorizations_recorded is True
    assert authorization.ready_for_separate_executor_invocation is True
    assert authorization.ready_for_production_cutover is False
    assert authorization.execution_allowed is False
    assert authorization.authorized_action_count == 1
    assert authorization.blocked_action_count == 0
    assert authorization.external_action_packet_sha256 == packet.sha256
    assert authorization.authorization_manifest_ref == authorization_manifest[
        "source_path"
    ]
    assert authorization.rows[0].area == "pi_hardware"
    assert authorization.rows[0].external_action_kind == "pi_hardware_validation"
    assert authorization.rows[0].status == "authorization_recorded"
    assert authorization.rows[0].operator_authorization_recorded is True
    assert authorization.rows[0].ready_for_separate_executor_invocation is True
    assert authorization.rows[0].execution_allowed is False
    assert authorization.external_call_performed_by_authorization is False
    assert authorization.safety_api_called_by_authorization is False
    assert authorization.runtime_safety_truth_mutated_by_authorization is False
    assert stored == authorization
    assert loaded == authorization

    with pytest.raises(ValueError, match="cannot claim production cutover"):
        ProductionSafetyQualificationExternalAuthorizationReport(
            **{
                **authorization.model_dump(mode="json"),
                "ready_for_production_cutover": True,
            }
        )


def test_production_safety_qualification_external_authorization_blocks_bad_manifests(
    tmp_path,
) -> None:
    report = run_production_safety_qualification_dossier(
        _dossier_manifest_payload(tmp_path, omit_area="transport_client"),
    )
    plan = evaluate_production_safety_qualification_gap_plan(report)
    pack = build_production_safety_qualification_evidence_request_pack(plan)
    _manifest, _source_package, _source_report, fulfillment = (
        _source_verified_fulfillment_report(tmp_path, pack)
    )
    remediation = evaluate_production_safety_qualification_remediation_readiness(
        plan,
        pack,
        fulfillment,
    )
    packet = build_production_safety_qualification_external_action_packet(remediation)
    key = _external_authorization_row_key(packet.rows[0])

    missing = evaluate_production_safety_qualification_external_authorization(
        packet,
        _external_authorization_manifest_payload(packet, omit_key=key),
    )
    wrong_kind = evaluate_production_safety_qualification_external_authorization(
        packet,
        _external_authorization_manifest_payload(packet, wrong_kind_key=key),
    )
    rejected = evaluate_production_safety_qualification_external_authorization(
        packet,
        _external_authorization_manifest_payload(packet, reject_key=key),
    )
    expired = evaluate_production_safety_qualification_external_authorization(
        packet,
        _external_authorization_manifest_payload(packet, expired_key=key),
    )
    missing_operator = (
        evaluate_production_safety_qualification_external_authorization(
            packet,
            _external_authorization_manifest_payload(
                packet,
                missing_operator_key=key,
            ),
        )
    )

    assert missing.status == "blocked_external_authorization_incomplete"
    assert missing.rows[0].status == "missing_authorization"
    assert "external_authorization_submission_missing" in missing.rows[0].blockers

    assert wrong_kind.rows[0].status == "mismatched_authorization"
    assert "external_action_kind_mismatch" in wrong_kind.rows[0].blockers

    assert rejected.rows[0].status == "rejected_authorization"
    assert "external_authorization_not_granted" in rejected.rows[0].blockers

    assert expired.rows[0].status == "expired_authorization"
    assert "external_authorization_expired" in expired.rows[0].blockers

    assert missing_operator.rows[0].status == "mismatched_authorization"
    assert "operator_identity_ref_missing" in missing_operator.rows[0].blockers

    blocked_report = run_production_safety_qualification_dossier(
        _dossier_manifest_payload(tmp_path, omit_area="outbound_delivery"),
    )
    blocked_plan = evaluate_production_safety_qualification_gap_plan(blocked_report)
    blocked_pack = build_production_safety_qualification_evidence_request_pack(
        blocked_plan
    )
    blocked_manifest, _blocked_source_package = (
        _fulfillment_manifest_and_source_package_payload(
            tmp_path,
            blocked_pack,
        )
    )
    blocked_fulfillment = (
        evaluate_production_safety_qualification_evidence_fulfillment(
            blocked_pack,
            blocked_manifest,
        )
    )
    blocked_remediation = evaluate_production_safety_qualification_remediation_readiness(
        blocked_plan,
        blocked_pack,
        blocked_fulfillment,
    )
    blocked_packet = build_production_safety_qualification_external_action_packet(
        blocked_remediation
    )
    blocked_authorization = (
        evaluate_production_safety_qualification_external_authorization(
            blocked_packet,
            _external_authorization_manifest_payload(blocked_packet),
        )
    )

    assert blocked_authorization.status == "blocked_external_authorization_incomplete"
    assert blocked_authorization.rows[0].status == "blocked_packet_incomplete"
    assert blocked_authorization.rows[0].operator_authorization_recorded is False

    with pytest.raises(ValueError, match="cannot perform effects"):
        ProductionSafetyQualificationExternalAuthorizationManifest(
            **{
                **_external_authorization_manifest_payload(packet),
                "external_call_performed_by_authorization_manifest": True,
            }
        )


def test_production_safety_qualification_external_authorization_cli_writes_report(
    tmp_path,
) -> None:
    report = run_production_safety_qualification_dossier(
        _dossier_manifest_payload(tmp_path, omit_area="live_provider_api"),
    )
    plan = evaluate_production_safety_qualification_gap_plan(report)
    pack = build_production_safety_qualification_evidence_request_pack(plan)
    _manifest, _source_package, _source_report, fulfillment = (
        _source_verified_fulfillment_report(tmp_path, pack)
    )
    remediation = evaluate_production_safety_qualification_remediation_readiness(
        plan,
        pack,
        fulfillment,
    )
    packet = build_production_safety_qualification_external_action_packet(
        remediation,
        source_path="prod://qualification/external-actions/provider-cli",
    )
    authorization_manifest = _external_authorization_manifest_payload(packet)
    packet_path = tmp_path / "external-action-packet.json"
    manifest_path = tmp_path / "external-authorization-manifest.json"
    output_path = tmp_path / "external-authorization-report.json"
    write_production_safety_qualification_external_action_packet(packet, packet_path)
    manifest_path.write_text(
        json.dumps(authorization_manifest),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "--external-authorization-packet",
            str(packet_path),
            "--external-authorization-manifest",
            str(manifest_path),
            "--external-authorization-output",
            str(output_path),
            "--source-path",
            "prod://qualification/external-authorization/from-cli",
        ]
    )
    loaded = load_production_safety_qualification_external_authorization_report(
        output_path
    )

    assert exit_code == 0
    assert loaded.status == "external_authorization_recorded"
    assert loaded.rows[0].area == "live_provider_api"
    assert loaded.rows[0].external_action_kind == "provider_api_qualification"
    assert loaded.ready_for_separate_executor_invocation is True
    assert loaded.execution_allowed is False


def test_production_safety_qualification_external_invocation_records_handoff_without_execution(
    tmp_path,
) -> None:
    report = run_production_safety_qualification_dossier(
        _dossier_manifest_payload(tmp_path, omit_area="pi_hardware"),
    )
    plan = evaluate_production_safety_qualification_gap_plan(report)
    pack = build_production_safety_qualification_evidence_request_pack(plan)
    _manifest, _source_package, _source_report, fulfillment = (
        _source_verified_fulfillment_report(tmp_path, pack)
    )
    remediation = evaluate_production_safety_qualification_remediation_readiness(
        plan,
        pack,
        fulfillment,
    )
    packet = build_production_safety_qualification_external_action_packet(
        remediation,
        source_path="prod://qualification/external-actions/pi-invoke",
    )
    authorization = evaluate_production_safety_qualification_external_authorization(
        packet,
        _external_authorization_manifest_payload(packet),
        source_path="prod://qualification/external-authorization/pi-invoke",
    )
    invocation_manifest = _external_invocation_manifest_payload(authorization)

    invocation = evaluate_production_safety_qualification_external_invocation(
        authorization,
        invocation_manifest,
        source_path="prod://qualification/external-invocation/pi-invoke",
    )
    output_path = tmp_path / "external-invocation-report.json"
    stored = write_production_safety_qualification_external_invocation_report(
        invocation,
        output_path,
    )
    loaded = load_production_safety_qualification_external_invocation_report(
        output_path
    )

    assert invocation.status == "external_invocation_handoff_recorded"
    assert invocation.all_invocation_handoffs_recorded is True
    assert invocation.ready_for_separate_executor_handoff is True
    assert invocation.ready_for_production_cutover is False
    assert invocation.execution_allowed is False
    assert invocation.invocation_handoff_count == 1
    assert invocation.blocked_invocation_count == 0
    assert invocation.external_authorization_report_sha256 == authorization.sha256
    assert invocation.rows[0].area == "pi_hardware"
    assert invocation.rows[0].external_action_kind == "pi_hardware_validation"
    assert invocation.rows[0].status == "invocation_handoff_recorded"
    assert invocation.rows[0].invocation_handoff_recorded is True
    assert invocation.rows[0].ready_for_separate_executor_handoff is True
    assert invocation.rows[0].execution_allowed is False
    assert invocation.external_call_performed_by_invocation is False
    assert invocation.safety_api_called_by_invocation is False
    assert invocation.runtime_safety_truth_mutated_by_invocation is False
    assert stored == invocation
    assert loaded == invocation

    with pytest.raises(ValueError, match="cannot claim production cutover"):
        ProductionSafetyQualificationExternalInvocationReport(
            **{
                **invocation.model_dump(mode="json"),
                "ready_for_production_cutover": True,
            }
        )


def test_production_safety_qualification_external_invocation_blocks_bad_requests(
    tmp_path,
) -> None:
    report = run_production_safety_qualification_dossier(
        _dossier_manifest_payload(tmp_path, omit_area="transport_client"),
    )
    plan = evaluate_production_safety_qualification_gap_plan(report)
    pack = build_production_safety_qualification_evidence_request_pack(plan)
    _manifest, _source_package, _source_report, fulfillment = (
        _source_verified_fulfillment_report(tmp_path, pack)
    )
    remediation = evaluate_production_safety_qualification_remediation_readiness(
        plan,
        pack,
        fulfillment,
    )
    packet = build_production_safety_qualification_external_action_packet(remediation)
    authorization = evaluate_production_safety_qualification_external_authorization(
        packet,
        _external_authorization_manifest_payload(packet),
    )
    key = _external_invocation_row_key(authorization.rows[0])

    missing = evaluate_production_safety_qualification_external_invocation(
        authorization,
        _external_invocation_manifest_payload(authorization, omit_key=key),
    )
    wrong_kind = evaluate_production_safety_qualification_external_invocation(
        authorization,
        _external_invocation_manifest_payload(authorization, wrong_kind_key=key),
    )
    no_request = evaluate_production_safety_qualification_external_invocation(
        authorization,
        _external_invocation_manifest_payload(authorization, no_request_key=key),
    )
    no_confirmation = evaluate_production_safety_qualification_external_invocation(
        authorization,
        _external_invocation_manifest_payload(
            authorization,
            no_confirmation_key=key,
        ),
    )
    missing_executor = evaluate_production_safety_qualification_external_invocation(
        authorization,
        _external_invocation_manifest_payload(
            authorization,
            missing_executor_key=key,
        ),
    )

    assert missing.status == "blocked_external_invocation_incomplete"
    assert missing.rows[0].status == "missing_invocation_request"
    assert "external_invocation_request_missing" in missing.rows[0].blockers

    assert wrong_kind.rows[0].status == "mismatched_invocation_request"
    assert "external_action_kind_mismatch" in wrong_kind.rows[0].blockers

    assert no_request.rows[0].status == "rejected_invocation_request"
    assert "external_invocation_not_requested" in no_request.rows[0].blockers

    assert no_confirmation.rows[0].status == "missing_operator_confirmation"
    assert (
        "external_invocation_operator_confirmation_missing"
        in no_confirmation.rows[0].blockers
    )

    assert missing_executor.rows[0].status == "mismatched_invocation_request"
    assert "external_executor_ref_missing" in missing_executor.rows[0].blockers

    blocked_report = run_production_safety_qualification_dossier(
        _dossier_manifest_payload(tmp_path, omit_area="outbound_delivery"),
    )
    blocked_plan = evaluate_production_safety_qualification_gap_plan(blocked_report)
    blocked_pack = build_production_safety_qualification_evidence_request_pack(
        blocked_plan
    )
    blocked_manifest, _blocked_source_package = (
        _fulfillment_manifest_and_source_package_payload(
            tmp_path,
            blocked_pack,
        )
    )
    blocked_fulfillment = (
        evaluate_production_safety_qualification_evidence_fulfillment(
            blocked_pack,
            blocked_manifest,
        )
    )
    blocked_remediation = evaluate_production_safety_qualification_remediation_readiness(
        blocked_plan,
        blocked_pack,
        blocked_fulfillment,
    )
    blocked_packet = build_production_safety_qualification_external_action_packet(
        blocked_remediation
    )
    blocked_authorization = (
        evaluate_production_safety_qualification_external_authorization(
            blocked_packet,
            _external_authorization_manifest_payload(blocked_packet),
        )
    )
    blocked_invocation = evaluate_production_safety_qualification_external_invocation(
        blocked_authorization,
        _external_invocation_manifest_payload(blocked_authorization),
    )

    assert blocked_invocation.status == "blocked_external_invocation_incomplete"
    assert blocked_invocation.rows[0].status == "blocked_authorization_incomplete"
    assert blocked_invocation.rows[0].invocation_handoff_recorded is False

    with pytest.raises(ValueError, match="cannot perform effects"):
        ProductionSafetyQualificationExternalInvocationManifest(
            **{
                **_external_invocation_manifest_payload(authorization),
                "external_call_performed_by_invocation_manifest": True,
            }
        )


def test_production_safety_qualification_external_invocation_cli_writes_report(
    tmp_path,
) -> None:
    report = run_production_safety_qualification_dossier(
        _dossier_manifest_payload(tmp_path, omit_area="live_provider_api"),
    )
    plan = evaluate_production_safety_qualification_gap_plan(report)
    pack = build_production_safety_qualification_evidence_request_pack(plan)
    _manifest, _source_package, _source_report, fulfillment = (
        _source_verified_fulfillment_report(tmp_path, pack)
    )
    remediation = evaluate_production_safety_qualification_remediation_readiness(
        plan,
        pack,
        fulfillment,
    )
    packet = build_production_safety_qualification_external_action_packet(
        remediation,
        source_path="prod://qualification/external-actions/provider-invoke-cli",
    )
    authorization = evaluate_production_safety_qualification_external_authorization(
        packet,
        _external_authorization_manifest_payload(packet),
        source_path="prod://qualification/external-authorization/provider-cli",
    )
    invocation_manifest = _external_invocation_manifest_payload(authorization)
    authorization_path = tmp_path / "external-authorization-report.json"
    manifest_path = tmp_path / "external-invocation-manifest.json"
    output_path = tmp_path / "external-invocation-report.json"
    write_production_safety_qualification_external_authorization_report(
        authorization,
        authorization_path,
    )
    manifest_path.write_text(
        json.dumps(invocation_manifest),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "--external-invocation-authorization-report",
            str(authorization_path),
            "--external-invocation-manifest",
            str(manifest_path),
            "--external-invocation-output",
            str(output_path),
            "--source-path",
            "prod://qualification/external-invocation/from-cli",
        ]
    )
    loaded = load_production_safety_qualification_external_invocation_report(
        output_path
    )

    assert exit_code == 0
    assert loaded.status == "external_invocation_handoff_recorded"
    assert loaded.rows[0].area == "live_provider_api"
    assert loaded.rows[0].external_action_kind == "provider_api_qualification"
    assert loaded.ready_for_separate_executor_handoff is True
    assert loaded.execution_allowed is False


def test_production_safety_qualification_external_result_intake_records_sanitized_receipt(
    tmp_path,
) -> None:
    report = run_production_safety_qualification_dossier(
        _dossier_manifest_payload(tmp_path, omit_area="pi_hardware"),
    )
    plan = evaluate_production_safety_qualification_gap_plan(report)
    pack = build_production_safety_qualification_evidence_request_pack(plan)
    _manifest, _source_package, _source_report, fulfillment = (
        _source_verified_fulfillment_report(tmp_path, pack)
    )
    remediation = evaluate_production_safety_qualification_remediation_readiness(
        plan,
        pack,
        fulfillment,
    )
    packet = build_production_safety_qualification_external_action_packet(
        remediation,
        source_path="prod://qualification/external-actions/pi-result",
    )
    authorization = evaluate_production_safety_qualification_external_authorization(
        packet,
        _external_authorization_manifest_payload(packet),
        source_path="prod://qualification/external-authorization/pi-result",
    )
    invocation = evaluate_production_safety_qualification_external_invocation(
        authorization,
        _external_invocation_manifest_payload(authorization),
        source_path="prod://qualification/external-invocation/pi-result",
    )
    result_manifest = _external_result_manifest_payload(invocation)

    result = evaluate_production_safety_qualification_external_result_intake(
        invocation,
        result_manifest,
        source_path="prod://qualification/external-result/pi-result",
    )
    output_path = tmp_path / "external-result-report.json"
    stored = write_production_safety_qualification_external_result_report(
        result,
        output_path,
    )
    loaded = load_production_safety_qualification_external_result_report(output_path)

    assert result.status == "external_results_recorded"
    assert result.all_result_receipts_recorded is True
    assert result.ready_for_evidence_fulfillment is True
    assert result.ready_for_production_cutover is False
    assert result.execution_allowed is False
    assert result.result_receipt_count == 1
    assert result.blocked_result_count == 0
    assert result.external_invocation_report_sha256 == invocation.sha256
    assert result.rows[0].area == "pi_hardware"
    assert result.rows[0].external_action_kind == "pi_hardware_validation"
    assert result.rows[0].status == "result_receipt_recorded"
    assert result.rows[0].result_receipt_recorded is True
    assert result.rows[0].ready_for_evidence_fulfillment is True
    assert result.rows[0].execution_allowed is False
    assert result.external_call_performed_by_result_intake is False
    assert result.safety_api_called_by_result_intake is False
    assert result.runtime_safety_truth_mutated_by_result_intake is False
    assert stored == result
    assert loaded == result

    with pytest.raises(ValueError, match="cannot claim production cutover"):
        ProductionSafetyQualificationExternalResultReport(
            **{
                **result.model_dump(mode="json"),
                "ready_for_production_cutover": True,
            }
        )


def test_production_safety_qualification_external_result_intake_blocks_bad_receipts(
    tmp_path,
) -> None:
    report = run_production_safety_qualification_dossier(
        _dossier_manifest_payload(tmp_path, omit_area="transport_client"),
    )
    plan = evaluate_production_safety_qualification_gap_plan(report)
    pack = build_production_safety_qualification_evidence_request_pack(plan)
    _manifest, _source_package, _source_report, fulfillment = (
        _source_verified_fulfillment_report(tmp_path, pack)
    )
    remediation = evaluate_production_safety_qualification_remediation_readiness(
        plan,
        pack,
        fulfillment,
    )
    packet = build_production_safety_qualification_external_action_packet(remediation)
    authorization = evaluate_production_safety_qualification_external_authorization(
        packet,
        _external_authorization_manifest_payload(packet),
    )
    invocation = evaluate_production_safety_qualification_external_invocation(
        authorization,
        _external_invocation_manifest_payload(authorization),
    )
    key = _external_result_row_key(invocation.rows[0])

    missing = evaluate_production_safety_qualification_external_result_intake(
        invocation,
        _external_result_manifest_payload(invocation, omit_key=key),
    )
    wrong_executor = evaluate_production_safety_qualification_external_result_intake(
        invocation,
        _external_result_manifest_payload(invocation, wrong_executor_key=key),
    )
    rejected = evaluate_production_safety_qualification_external_result_intake(
        invocation,
        _external_result_manifest_payload(invocation, reject_key=key),
    )
    unverified = evaluate_production_safety_qualification_external_result_intake(
        invocation,
        _external_result_manifest_payload(invocation, unverified_source_key=key),
    )
    missing_reviewer = evaluate_production_safety_qualification_external_result_intake(
        invocation,
        _external_result_manifest_payload(invocation, missing_reviewer_key=key),
    )

    assert missing.status == "blocked_external_results_incomplete"
    assert missing.rows[0].status == "missing_result_receipt"
    assert "external_result_receipt_missing" in missing.rows[0].blockers

    assert wrong_executor.rows[0].status == "mismatched_result_receipt"
    assert "external_executor_ref_mismatch" in wrong_executor.rows[0].blockers

    assert rejected.rows[0].status == "rejected_result_receipt"
    assert "external_result_receipt_not_accepted" in rejected.rows[0].blockers

    assert unverified.rows[0].status == "unverified_result_source"
    assert "external_result_source_integrity_missing" in unverified.rows[0].blockers

    assert missing_reviewer.rows[0].status == "mismatched_result_receipt"
    assert "reviewer_ref_missing" in missing_reviewer.rows[0].blockers

    blocked_report = run_production_safety_qualification_dossier(
        _dossier_manifest_payload(tmp_path, omit_area="outbound_delivery"),
    )
    blocked_plan = evaluate_production_safety_qualification_gap_plan(blocked_report)
    blocked_pack = build_production_safety_qualification_evidence_request_pack(
        blocked_plan
    )
    blocked_manifest, _blocked_source_package = (
        _fulfillment_manifest_and_source_package_payload(
            tmp_path,
            blocked_pack,
        )
    )
    blocked_fulfillment = (
        evaluate_production_safety_qualification_evidence_fulfillment(
            blocked_pack,
            blocked_manifest,
        )
    )
    blocked_remediation = evaluate_production_safety_qualification_remediation_readiness(
        blocked_plan,
        blocked_pack,
        blocked_fulfillment,
    )
    blocked_packet = build_production_safety_qualification_external_action_packet(
        blocked_remediation
    )
    blocked_authorization = (
        evaluate_production_safety_qualification_external_authorization(
            blocked_packet,
            _external_authorization_manifest_payload(blocked_packet),
        )
    )
    blocked_invocation = evaluate_production_safety_qualification_external_invocation(
        blocked_authorization,
        _external_invocation_manifest_payload(blocked_authorization),
    )
    blocked_result = evaluate_production_safety_qualification_external_result_intake(
        blocked_invocation,
        _external_result_manifest_payload(blocked_invocation),
    )

    assert blocked_result.status == "blocked_external_results_incomplete"
    assert blocked_result.rows[0].status == "blocked_invocation_incomplete"
    assert blocked_result.rows[0].result_receipt_recorded is False

    with pytest.raises(ValueError, match="cannot perform effects"):
        ProductionSafetyQualificationExternalResultManifest(
            **{
                **_external_result_manifest_payload(invocation),
                "external_call_performed_by_result_manifest": True,
            }
        )


def test_production_safety_qualification_external_result_intake_cli_writes_report(
    tmp_path,
) -> None:
    report = run_production_safety_qualification_dossier(
        _dossier_manifest_payload(tmp_path, omit_area="live_provider_api"),
    )
    plan = evaluate_production_safety_qualification_gap_plan(report)
    pack = build_production_safety_qualification_evidence_request_pack(plan)
    _manifest, _source_package, _source_report, fulfillment = (
        _source_verified_fulfillment_report(tmp_path, pack)
    )
    remediation = evaluate_production_safety_qualification_remediation_readiness(
        plan,
        pack,
        fulfillment,
    )
    packet = build_production_safety_qualification_external_action_packet(
        remediation,
        source_path="prod://qualification/external-actions/provider-result-cli",
    )
    authorization = evaluate_production_safety_qualification_external_authorization(
        packet,
        _external_authorization_manifest_payload(packet),
        source_path="prod://qualification/external-authorization/provider-result-cli",
    )
    invocation = evaluate_production_safety_qualification_external_invocation(
        authorization,
        _external_invocation_manifest_payload(authorization),
        source_path="prod://qualification/external-invocation/provider-result-cli",
    )
    result_manifest = _external_result_manifest_payload(invocation)
    invocation_path = tmp_path / "external-invocation-report.json"
    manifest_path = tmp_path / "external-result-manifest.json"
    output_path = tmp_path / "external-result-report.json"
    write_production_safety_qualification_external_invocation_report(
        invocation,
        invocation_path,
    )
    manifest_path.write_text(json.dumps(result_manifest), encoding="utf-8")

    exit_code = main(
        [
            "--external-result-invocation-report",
            str(invocation_path),
            "--external-result-manifest",
            str(manifest_path),
            "--external-result-output",
            str(output_path),
            "--source-path",
            "prod://qualification/external-result/from-cli",
        ]
    )
    loaded = load_production_safety_qualification_external_result_report(output_path)

    assert exit_code == 0
    assert loaded.status == "external_results_recorded"
    assert loaded.rows[0].area == "live_provider_api"
    assert loaded.rows[0].external_action_kind == "provider_api_qualification"
    assert loaded.ready_for_evidence_fulfillment is True
    assert loaded.execution_allowed is False


def test_production_safety_qualification_external_result_bridge_builds_fulfillment_manifest(
    tmp_path,
) -> None:
    report = run_production_safety_qualification_dossier(
        _dossier_manifest_payload(tmp_path, omit_area="transport_client"),
    )
    plan = evaluate_production_safety_qualification_gap_plan(report)
    pack = build_production_safety_qualification_evidence_request_pack(plan)
    _manifest, _source_package, _source_report, fulfillment = (
        _source_verified_fulfillment_report(tmp_path, pack)
    )
    remediation = evaluate_production_safety_qualification_remediation_readiness(
        plan,
        pack,
        fulfillment,
    )
    packet = build_production_safety_qualification_external_action_packet(remediation)
    authorization = evaluate_production_safety_qualification_external_authorization(
        packet,
        _external_authorization_manifest_payload(packet),
    )
    invocation = evaluate_production_safety_qualification_external_invocation(
        authorization,
        _external_invocation_manifest_payload(authorization),
    )
    result = evaluate_production_safety_qualification_external_result_intake(
        invocation,
        _external_result_manifest_payload(invocation, request_pack=pack),
    )

    bridge = build_production_safety_qualification_evidence_fulfillment_manifest_from_external_results(
        pack,
        result,
        source_path="prod://qualification/external-result-bridge/transport",
    )
    output_path = tmp_path / "external-result-bridge.json"
    stored = (
        write_production_safety_qualification_external_result_evidence_bridge_report(
            bridge,
            output_path,
        )
    )
    loaded = load_production_safety_qualification_external_result_evidence_bridge_report(
        output_path
    )

    assert bridge.status == "external_result_bridge_ready"
    assert bridge.ready_for_fulfillment_intake is True
    assert bridge.ready_for_production_cutover is False
    assert bridge.execution_allowed is False
    assert bridge.bridged_request_count == pack.request_count
    assert bridge.blocked_request_count == 0
    assert bridge.fulfillment_manifest is not None
    assert bridge.fulfillment_manifest.request_pack_ref == pack.source_path
    assert len(bridge.fulfillment_manifest.submissions) == pack.request_count
    assert {row.status for row in bridge.rows} == {
        "bridged_to_fulfillment_submission"
    }
    assert stored == bridge
    assert loaded == bridge

    still_gated = evaluate_production_safety_qualification_evidence_fulfillment(
        pack,
        bridge.fulfillment_manifest,
    )
    assert (
        still_gated.status
        == "blocked_fulfillment_source_integrity_unverified"
    )
    assert still_gated.source_unverified_request_count == pack.request_count

    with pytest.raises(ValueError, match="cannot claim cutover"):
        ProductionSafetyQualificationExternalResultEvidenceBridgeReport(
            **{
                **bridge.model_dump(mode="json"),
                "ready_for_production_cutover": True,
            }
        )


def test_production_safety_qualification_external_result_bridge_blocks_bad_artifacts(
    tmp_path,
) -> None:
    report = run_production_safety_qualification_dossier(
        _dossier_manifest_payload(tmp_path, omit_area="outbound_delivery"),
    )
    plan = evaluate_production_safety_qualification_gap_plan(report)
    pack = build_production_safety_qualification_evidence_request_pack(plan)
    _manifest, _source_package, _source_report, fulfillment = (
        _source_verified_fulfillment_report(tmp_path, pack)
    )
    remediation = evaluate_production_safety_qualification_remediation_readiness(
        plan,
        pack,
        fulfillment,
    )
    packet = build_production_safety_qualification_external_action_packet(remediation)
    authorization = evaluate_production_safety_qualification_external_authorization(
        packet,
        _external_authorization_manifest_payload(packet),
    )
    invocation = evaluate_production_safety_qualification_external_invocation(
        authorization,
        _external_invocation_manifest_payload(authorization),
    )
    key = _external_result_row_key(invocation.rows[0])

    generic_result = evaluate_production_safety_qualification_external_result_intake(
        invocation,
        _external_result_manifest_payload(invocation),
    )
    wrong_kind_bridge = build_production_safety_qualification_evidence_fulfillment_manifest_from_external_results(
        pack,
        generic_result,
    )

    assert wrong_kind_bridge.status == "blocked_external_result_bridge_incomplete"
    assert wrong_kind_bridge.ready_for_fulfillment_intake is False
    assert wrong_kind_bridge.fulfillment_manifest is None
    assert {row.status for row in wrong_kind_bridge.rows} == {
        "mismatched_result_artifact"
    }
    assert {
        blocker
        for row in wrong_kind_bridge.rows
        for blocker in row.blockers
    } == {"external_result_artifact_kind_not_requested"}

    rejected_result = evaluate_production_safety_qualification_external_result_intake(
        invocation,
        _external_result_manifest_payload(
            invocation,
            request_pack=pack,
            reject_provided_artifacts_key=key,
        ),
    )
    rejected_bridge = build_production_safety_qualification_evidence_fulfillment_manifest_from_external_results(
        pack,
        rejected_result,
    )

    assert rejected_bridge.status == "blocked_external_result_bridge_incomplete"
    assert {row.status for row in rejected_bridge.rows} == {
        "mismatched_result_artifact"
    }
    assert {
        blocker
        for row in rejected_bridge.rows
        for blocker in row.blockers
    } == {"external_result_artifact_not_accepted"}

    empty_result = ProductionSafetyQualificationExternalResultReport(
        source_path="prod://qualification/external-result/no-rows",
        sha256="0" * 64,
        status="no_external_result_required",
        external_invocation_report_ref=generic_result.external_invocation_report_ref,
        external_invocation_report_sha256=(
            generic_result.external_invocation_report_sha256
        ),
        result_manifest_ref=generic_result.result_manifest_ref,
        result_manifest_sha256=generic_result.result_manifest_sha256,
        external_authorization_report_ref=(
            generic_result.external_authorization_report_ref
        ),
        external_authorization_report_sha256=(
            generic_result.external_authorization_report_sha256
        ),
        external_action_packet_ref=generic_result.external_action_packet_ref,
        external_action_packet_sha256=generic_result.external_action_packet_sha256,
        remediation_report_ref=generic_result.remediation_report_ref,
        remediation_report_sha256=generic_result.remediation_report_sha256,
        all_result_receipts_recorded=True,
    )
    missing_bridge = build_production_safety_qualification_evidence_fulfillment_manifest_from_external_results(
        pack,
        empty_result,
    )

    assert missing_bridge.status == "blocked_external_result_bridge_incomplete"
    assert {row.status for row in missing_bridge.rows} == {
        "missing_result_for_request"
    }
    assert {
        blocker
        for row in missing_bridge.rows
        for blocker in row.blockers
    } == {"external_result_row_missing_for_request"}

    missing_receipt_result = evaluate_production_safety_qualification_external_result_intake(
        invocation,
        _external_result_manifest_payload(
            invocation,
            request_pack=pack,
            omit_key=key,
        ),
    )
    not_ready_bridge = build_production_safety_qualification_evidence_fulfillment_manifest_from_external_results(
        pack,
        missing_receipt_result,
    )

    assert not_ready_bridge.status == "blocked_external_result_bridge_incomplete"
    assert {row.status for row in not_ready_bridge.rows} == {
        "blocked_result_not_ready"
    }
    assert {
        blocker
        for row in not_ready_bridge.rows
        for blocker in row.blockers
    } == {"external_result_receipt_missing"}


def test_production_safety_qualification_external_result_bridge_cli_writes_outputs(
    tmp_path,
) -> None:
    report = run_production_safety_qualification_dossier(
        _dossier_manifest_payload(tmp_path, omit_area="pi_hardware"),
    )
    plan = evaluate_production_safety_qualification_gap_plan(report)
    pack = build_production_safety_qualification_evidence_request_pack(plan)
    _manifest, _source_package, _source_report, fulfillment = (
        _source_verified_fulfillment_report(tmp_path, pack)
    )
    remediation = evaluate_production_safety_qualification_remediation_readiness(
        plan,
        pack,
        fulfillment,
    )
    packet = build_production_safety_qualification_external_action_packet(remediation)
    authorization = evaluate_production_safety_qualification_external_authorization(
        packet,
        _external_authorization_manifest_payload(packet),
    )
    invocation = evaluate_production_safety_qualification_external_invocation(
        authorization,
        _external_invocation_manifest_payload(authorization),
    )
    result = evaluate_production_safety_qualification_external_result_intake(
        invocation,
        _external_result_manifest_payload(invocation, request_pack=pack),
    )
    pack_path = tmp_path / "request-pack.json"
    result_path = tmp_path / "external-result-report.json"
    bridge_path = tmp_path / "external-result-bridge.json"
    manifest_path = tmp_path / "bridged-fulfillment-manifest.json"
    write_production_safety_qualification_evidence_request_pack(pack, pack_path)
    write_production_safety_qualification_external_result_report(result, result_path)

    exit_code = main(
        [
            "--external-result-bridge-request-pack",
            str(pack_path),
            "--external-result-bridge-report",
            str(result_path),
            "--external-result-bridge-output",
            str(bridge_path),
            "--external-result-bridge-fulfillment-output",
            str(manifest_path),
            "--source-path",
            "prod://qualification/external-result-bridge/from-cli",
        ]
    )
    loaded_bridge = (
        load_production_safety_qualification_external_result_evidence_bridge_report(
            bridge_path
        )
    )
    loaded_manifest = load_production_safety_qualification_evidence_fulfillment_manifest(
        manifest_path
    )

    assert exit_code == 0
    assert loaded_bridge.status == "external_result_bridge_ready"
    assert loaded_bridge.ready_for_fulfillment_intake is True
    assert loaded_bridge.fulfillment_manifest == loaded_manifest
    assert loaded_manifest.request_pack_ref == pack.source_path
    assert len(loaded_manifest.submissions) == pack.request_count

    still_gated = evaluate_production_safety_qualification_evidence_fulfillment(
        pack,
        loaded_manifest,
    )
    assert (
        still_gated.status
        == "blocked_fulfillment_source_integrity_unverified"
    )


def test_production_safety_qualification_external_result_closure_reaches_remediation_ready(
    tmp_path,
) -> None:
    report = run_production_safety_qualification_dossier(
        _dossier_manifest_payload(tmp_path, omit_area="field_device_validator"),
    )
    plan = evaluate_production_safety_qualification_gap_plan(report)
    pack = build_production_safety_qualification_evidence_request_pack(plan)
    _manifest, _source_package, _source_report, fulfillment = (
        _source_verified_fulfillment_report(tmp_path, pack)
    )
    remediation = evaluate_production_safety_qualification_remediation_readiness(
        plan,
        pack,
        fulfillment,
    )
    packet = build_production_safety_qualification_external_action_packet(remediation)
    authorization = evaluate_production_safety_qualification_external_authorization(
        packet,
        _external_authorization_manifest_payload(packet),
    )
    invocation = evaluate_production_safety_qualification_external_invocation(
        authorization,
        _external_invocation_manifest_payload(authorization),
    )
    artifact_hashes, artifact_paths = _external_result_local_artifact_files(
        tmp_path,
        pack,
    )
    result = evaluate_production_safety_qualification_external_result_intake(
        invocation,
        _external_result_manifest_payload(
            invocation,
            request_pack=pack,
            artifact_hashes_by_request_key=artifact_hashes,
        ),
    )
    bridge = build_production_safety_qualification_evidence_fulfillment_manifest_from_external_results(
        pack,
        result,
        source_path="prod://qualification/external-result-bridge/field-device",
    )
    closure_source_package = _external_result_source_package_payload_for_bridge(
        bridge,
        artifact_paths,
    )

    closure = evaluate_production_safety_qualification_external_result_remediation_closure(
        plan,
        pack,
        bridge,
        closure_source_package,
        root_path=tmp_path,
        source_path="prod://qualification/external-result-closure/field-device",
    )
    output_path = tmp_path / "external-result-closure.json"
    stored = (
        write_production_safety_qualification_external_result_remediation_closure_report(
            closure,
            output_path,
        )
    )
    loaded = load_production_safety_qualification_external_result_remediation_closure_report(
        output_path
    )

    assert (
        closure.status
        == "external_result_remediation_ready_for_dossier_rerun"
    )
    assert closure.ready_for_dossier_rerun is True
    assert closure.ready_for_production_cutover is False
    assert closure.execution_allowed is False
    assert closure.bridge_report == bridge
    assert closure.source_integrity_report is not None
    assert (
        closure.source_integrity_report.status
        == "fulfillment_source_integrity_verified"
    )
    assert closure.source_integrity_report.all_fulfillment_sources_verified is True
    assert closure.fulfillment_report is not None
    assert (
        closure.fulfillment_report.status
        == "evidence_request_fulfillment_verified"
    )
    assert closure.remediation_report is not None
    assert closure.remediation_report.status == "ready_for_dossier_rerun"
    assert stored == closure
    assert loaded == closure

    with pytest.raises(ValueError, match="cannot claim cutover"):
        ProductionSafetyQualificationExternalResultRemediationClosureReport(
            **{
                **closure.model_dump(mode="json"),
                "ready_for_production_cutover": True,
            }
        )


def test_production_safety_qualification_external_result_closure_blocks_source_package_gaps(
    tmp_path,
) -> None:
    report = run_production_safety_qualification_dossier(
        _dossier_manifest_payload(tmp_path, omit_area="resident_freshness_attestor"),
    )
    plan = evaluate_production_safety_qualification_gap_plan(report)
    pack = build_production_safety_qualification_evidence_request_pack(plan)
    _manifest, _source_package, _source_report, fulfillment = (
        _source_verified_fulfillment_report(tmp_path, pack)
    )
    remediation = evaluate_production_safety_qualification_remediation_readiness(
        plan,
        pack,
        fulfillment,
    )
    packet = build_production_safety_qualification_external_action_packet(remediation)
    authorization = evaluate_production_safety_qualification_external_authorization(
        packet,
        _external_authorization_manifest_payload(packet),
    )
    invocation = evaluate_production_safety_qualification_external_invocation(
        authorization,
        _external_invocation_manifest_payload(authorization),
    )
    artifact_hashes, artifact_paths = _external_result_local_artifact_files(
        tmp_path,
        pack,
    )
    result = evaluate_production_safety_qualification_external_result_intake(
        invocation,
        _external_result_manifest_payload(
            invocation,
            request_pack=pack,
            artifact_hashes_by_request_key=artifact_hashes,
        ),
    )
    bridge = build_production_safety_qualification_evidence_fulfillment_manifest_from_external_results(
        pack,
        result,
    )

    missing_package = (
        evaluate_production_safety_qualification_external_result_remediation_closure(
            plan,
            pack,
            bridge,
        )
    )

    assert (
        missing_package.status
        == "blocked_external_result_source_package_missing"
    )
    assert missing_package.ready_for_dossier_rerun is False
    assert missing_package.source_integrity_report is None
    assert missing_package.fulfillment_report is None
    assert missing_package.remediation_report is None

    assert bridge.fulfillment_manifest is not None
    wrong_ref = bridge.fulfillment_manifest.submissions[0].submitted_artifact_ref
    bad_source_package = _external_result_source_package_payload_for_bridge(
        bridge,
        artifact_paths,
        wrong_hash_ref=wrong_ref,
    )
    failed_source = (
        evaluate_production_safety_qualification_external_result_remediation_closure(
            plan,
            pack,
            bridge,
            bad_source_package,
            root_path=tmp_path,
        )
    )

    assert (
        failed_source.status
        == "blocked_external_result_source_integrity_failed"
    )
    assert failed_source.ready_for_dossier_rerun is False
    assert failed_source.source_integrity_report is not None
    assert (
        failed_source.source_integrity_report.status
        == "blocked_fulfillment_source_integrity_failed"
    )
    assert failed_source.fulfillment_report is not None
    assert (
        failed_source.fulfillment_report.status
        == "blocked_fulfillment_source_integrity_unverified"
    )
    assert failed_source.remediation_report is not None
    assert failed_source.remediation_report.status == "blocked_remediation_incomplete"


def test_production_safety_qualification_external_result_closure_cli_writes_report(
    tmp_path,
) -> None:
    report = run_production_safety_qualification_dossier(
        _dossier_manifest_payload(tmp_path, omit_area="connector_health_endpoint"),
    )
    plan = evaluate_production_safety_qualification_gap_plan(report)
    pack = build_production_safety_qualification_evidence_request_pack(plan)
    _manifest, _source_package, _source_report, fulfillment = (
        _source_verified_fulfillment_report(tmp_path, pack)
    )
    remediation = evaluate_production_safety_qualification_remediation_readiness(
        plan,
        pack,
        fulfillment,
    )
    packet = build_production_safety_qualification_external_action_packet(remediation)
    authorization = evaluate_production_safety_qualification_external_authorization(
        packet,
        _external_authorization_manifest_payload(packet),
    )
    invocation = evaluate_production_safety_qualification_external_invocation(
        authorization,
        _external_invocation_manifest_payload(authorization),
    )
    artifact_hashes, artifact_paths = _external_result_local_artifact_files(
        tmp_path,
        pack,
    )
    result = evaluate_production_safety_qualification_external_result_intake(
        invocation,
        _external_result_manifest_payload(
            invocation,
            request_pack=pack,
            artifact_hashes_by_request_key=artifact_hashes,
        ),
    )
    bridge = build_production_safety_qualification_evidence_fulfillment_manifest_from_external_results(
        pack,
        result,
        source_path="prod://qualification/external-result-bridge/health",
    )
    source_package = _external_result_source_package_payload_for_bridge(
        bridge,
        artifact_paths,
    )
    plan_path = tmp_path / "gap-plan.json"
    pack_path = tmp_path / "request-pack.json"
    bridge_path = tmp_path / "bridge.json"
    source_package_path = tmp_path / "source-package.json"
    output_path = tmp_path / "closure.json"
    write_production_safety_qualification_gap_plan(plan, plan_path)
    write_production_safety_qualification_evidence_request_pack(pack, pack_path)
    write_production_safety_qualification_external_result_evidence_bridge_report(
        bridge,
        bridge_path,
    )
    source_package_path.write_text(json.dumps(source_package), encoding="utf-8")

    exit_code = main(
        [
            "--external-result-closure-gap-plan",
            str(plan_path),
            "--external-result-closure-request-pack",
            str(pack_path),
            "--external-result-closure-bridge-report",
            str(bridge_path),
            "--external-result-closure-source-package",
            str(source_package_path),
            "--external-result-closure-output",
            str(output_path),
            "--source-root",
            str(tmp_path),
            "--source-path",
            "prod://qualification/external-result-closure/from-cli",
        ]
    )
    loaded = load_production_safety_qualification_external_result_remediation_closure_report(
        output_path
    )

    assert exit_code == 0
    assert (
        loaded.status
        == "external_result_remediation_ready_for_dossier_rerun"
    )
    assert loaded.ready_for_dossier_rerun is True
    assert loaded.ready_for_production_cutover is False
    assert loaded.source_integrity_report is not None
    assert loaded.fulfillment_report is not None
    assert loaded.remediation_report is not None


def test_production_safety_qualification_dossier_rerun_intake_runs_ready_closure_without_cutover(
    tmp_path,
) -> None:
    closure = _ready_external_result_remediation_closure(
        tmp_path,
        omit_area="field_device_validator",
        source_path="prod://qualification/external-result-closure/field-device-ready",
    )

    rerun = evaluate_production_safety_qualification_dossier_rerun_intake(
        closure,
        _dossier_manifest_payload(tmp_path),
        source_integrity_output_dir=tmp_path / "rerun-source-integrity",
        admission_output_dir=tmp_path / "rerun-admission",
        receipt_output_dir=tmp_path / "rerun-receipts",
        source_path="prod://qualification/dossier-rerun/field-device-ready",
    )
    output_path = tmp_path / "dossier-rerun.json"
    stored = write_production_safety_qualification_dossier_rerun_report(
        rerun,
        output_path,
    )
    loaded = load_production_safety_qualification_dossier_rerun_report(output_path)

    assert rerun.status == "dossier_rerun_ready_for_cutover_review"
    assert rerun.local_dossier_validator_executed is True
    assert rerun.dossier_report is not None
    assert rerun.dossier_status == "dossier_ready_for_production_cutover"
    assert rerun.cutover_audit_status == "ready_for_production_cutover"
    assert rerun.dossier_report_ready_for_cutover is True
    assert rerun.ready_for_production_cutover is False
    assert rerun.execution_allowed is False
    assert stored == rerun
    assert loaded == rerun

    with pytest.raises(ValueError, match="cannot claim production cutover"):
        ProductionSafetyQualificationDossierRerunReport(
            **{
                **rerun.model_dump(mode="json"),
                "ready_for_production_cutover": True,
            }
        )


def test_production_safety_qualification_dossier_rerun_intake_blocks_incomplete_closure_and_failed_rerun(
    tmp_path,
) -> None:
    report = run_production_safety_qualification_dossier(
        _dossier_manifest_payload(tmp_path, omit_area="resident_freshness_attestor"),
    )
    plan = evaluate_production_safety_qualification_gap_plan(report)
    pack = build_production_safety_qualification_evidence_request_pack(plan)
    _manifest, _source_package, _source_report, fulfillment = (
        _source_verified_fulfillment_report(tmp_path, pack)
    )
    remediation = evaluate_production_safety_qualification_remediation_readiness(
        plan,
        pack,
        fulfillment,
    )
    packet = build_production_safety_qualification_external_action_packet(remediation)
    authorization = evaluate_production_safety_qualification_external_authorization(
        packet,
        _external_authorization_manifest_payload(packet),
    )
    invocation = evaluate_production_safety_qualification_external_invocation(
        authorization,
        _external_invocation_manifest_payload(authorization),
    )
    artifact_hashes, _artifact_paths = _external_result_local_artifact_files(
        tmp_path,
        pack,
    )
    result = evaluate_production_safety_qualification_external_result_intake(
        invocation,
        _external_result_manifest_payload(
            invocation,
            request_pack=pack,
            artifact_hashes_by_request_key=artifact_hashes,
        ),
    )
    bridge = build_production_safety_qualification_evidence_fulfillment_manifest_from_external_results(
        pack,
        result,
    )
    blocked_closure = (
        evaluate_production_safety_qualification_external_result_remediation_closure(
            plan,
            pack,
            bridge,
        )
    )

    blocked_rerun = evaluate_production_safety_qualification_dossier_rerun_intake(
        blocked_closure,
        _dossier_manifest_payload(tmp_path),
    )
    ready_closure = _ready_external_result_remediation_closure(
        tmp_path,
        omit_area="connector_health_endpoint",
        source_path="prod://qualification/external-result-closure/health-ready",
    )
    failed_rerun = evaluate_production_safety_qualification_dossier_rerun_intake(
        ready_closure,
        _dossier_manifest_payload(tmp_path, omit_area="pi_hardware"),
    )

    assert (
        blocked_rerun.status
        == "blocked_external_result_remediation_incomplete"
    )
    assert blocked_rerun.local_dossier_validator_executed is False
    assert blocked_rerun.dossier_report is None
    assert failed_rerun.status == "blocked_dossier_rerun_incomplete"
    assert failed_rerun.local_dossier_validator_executed is True
    assert failed_rerun.dossier_report is not None
    assert failed_rerun.dossier_status == "blocked_dossier_incomplete"
    assert failed_rerun.dossier_report_ready_for_cutover is False
    assert failed_rerun.ready_for_production_cutover is False


def test_production_safety_qualification_dossier_rerun_cli_writes_report(
    tmp_path,
) -> None:
    closure = _ready_external_result_remediation_closure(
        tmp_path,
        omit_area="transport_client",
        source_path="prod://qualification/external-result-closure/transport-ready",
    )
    manifest_payload = _dossier_manifest_payload(tmp_path)
    closure_path = tmp_path / "external-result-closure.json"
    manifest_path = tmp_path / "dossier-manifest.json"
    output_path = tmp_path / "dossier-rerun-report.json"
    write_production_safety_qualification_external_result_remediation_closure_report(
        closure,
        closure_path,
    )
    manifest_path.write_text(json.dumps(manifest_payload), encoding="utf-8")

    exit_code = main(
        [
            "--dossier-rerun-closure-report",
            str(closure_path),
            "--dossier-rerun-manifest",
            str(manifest_path),
            "--dossier-rerun-output",
            str(output_path),
            "--source-integrity-output-dir",
            str(tmp_path / "cli-rerun-source-integrity"),
            "--admission-output-dir",
            str(tmp_path / "cli-rerun-admission"),
            "--receipt-output-dir",
            str(tmp_path / "cli-rerun-receipts"),
            "--source-path",
            "prod://qualification/dossier-rerun/from-cli",
        ]
    )
    loaded = load_production_safety_qualification_dossier_rerun_report(output_path)

    assert exit_code == 0
    assert loaded.status == "dossier_rerun_ready_for_cutover_review"
    assert loaded.local_dossier_validator_executed is True
    assert loaded.dossier_report is not None
    assert loaded.dossier_report_ready_for_cutover is True
    assert loaded.ready_for_production_cutover is False
    assert loaded.execution_allowed is False


def test_production_safety_qualification_cutover_authorization_records_review_without_execution(
    tmp_path,
) -> None:
    rerun = _ready_dossier_rerun_report(
        tmp_path,
        omit_area="field_device_validator",
        source_path="prod://qualification/dossier-rerun/cutover-ready",
    )
    report = evaluate_production_safety_qualification_cutover_authorization(
        rerun,
        _cutover_authorization_manifest_payload(rerun),
        source_path="prod://qualification/cutover-authorization/report",
    )
    output_path = tmp_path / "cutover-authorization.json"
    stored = write_production_safety_qualification_cutover_authorization_report(
        report,
        output_path,
    )
    loaded = load_production_safety_qualification_cutover_authorization_report(
        output_path
    )

    assert report.status == "cutover_authorization_recorded"
    assert report.cutover_authorization_recorded is True
    assert report.ready_for_human_cutover_review is True
    assert report.ready_for_production_cutover is False
    assert report.execution_allowed is False
    assert report.dossier_status == "dossier_ready_for_production_cutover"
    assert report.cutover_audit_status == "ready_for_production_cutover"
    assert report.explicit_confirmation_phrase == (
        PRODUCTION_SAFETY_CUTOVER_REVIEW_CONFIRMATION
    )
    assert stored == report
    assert loaded == report

    with pytest.raises(ValueError, match="cannot claim production cutover"):
        ProductionSafetyQualificationCutoverAuthorizationReport(
            **{
                **report.model_dump(mode="json"),
                "ready_for_production_cutover": True,
            }
        )


def test_production_safety_qualification_cutover_authorization_blocks_unready_rerun(
    tmp_path,
) -> None:
    closure = _ready_external_result_remediation_closure(
        tmp_path,
        omit_area="connector_health_endpoint",
        source_path="prod://qualification/external-result-closure/cutover-unready",
    )
    rerun = evaluate_production_safety_qualification_dossier_rerun_intake(
        closure,
        _dossier_manifest_payload(tmp_path, omit_area="pi_hardware"),
        source_path="prod://qualification/dossier-rerun/cutover-unready",
    )

    report = evaluate_production_safety_qualification_cutover_authorization(
        rerun,
        _cutover_authorization_manifest_payload(rerun),
    )

    assert report.status == "blocked_dossier_rerun_not_ready"
    assert report.cutover_authorization_recorded is False
    assert report.ready_for_human_cutover_review is False
    assert report.ready_for_production_cutover is False
    assert "dossier_rerun_not_ready_for_cutover_review" in report.blockers


def test_production_safety_qualification_cutover_authorization_blocks_manifest_gaps(
    tmp_path,
) -> None:
    rerun = _ready_dossier_rerun_report(
        tmp_path,
        omit_area="transport_client",
        source_path="prod://qualification/dossier-rerun/cutover-manifest-gaps",
    )

    missing = evaluate_production_safety_qualification_cutover_authorization(
        rerun,
        _cutover_authorization_manifest_payload(rerun, omit_operator=True),
    )
    rejected = evaluate_production_safety_qualification_cutover_authorization(
        rerun,
        _cutover_authorization_manifest_payload(rerun, authorized=False),
    )
    expired = evaluate_production_safety_qualification_cutover_authorization(
        rerun,
        _cutover_authorization_manifest_payload(rerun, expired=True),
    )
    mismatched = evaluate_production_safety_qualification_cutover_authorization(
        rerun,
        _cutover_authorization_manifest_payload(
            rerun,
            confirmation_phrase="AUTHORIZE SCOUT PRODUCTION CUTOVER",
        ),
    )

    assert missing.status == "missing_cutover_authorization"
    assert "operator_identity_ref_missing" in missing.blockers
    assert rejected.status == "rejected_cutover_authorization"
    assert "cutover_authorization_not_granted" in rejected.blockers
    assert expired.status == "expired_cutover_authorization"
    assert "cutover_authorization_expired" in expired.blockers
    assert mismatched.status == "mismatched_cutover_authorization"
    assert "explicit_confirmation_phrase_mismatch" in mismatched.blockers


def test_production_safety_qualification_cutover_authorization_cli_writes_report(
    tmp_path,
) -> None:
    rerun = _ready_dossier_rerun_report(
        tmp_path,
        omit_area="outbound_delivery",
        source_path="prod://qualification/dossier-rerun/cutover-cli",
    )
    rerun_path = tmp_path / "dossier-rerun.json"
    manifest_path = tmp_path / "cutover-authorization-manifest.json"
    output_path = tmp_path / "cutover-authorization-report.json"
    write_production_safety_qualification_dossier_rerun_report(rerun, rerun_path)
    manifest_path.write_text(
        json.dumps(_cutover_authorization_manifest_payload(rerun)),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "--cutover-authorization-dossier-rerun-report",
            str(rerun_path),
            "--cutover-authorization-manifest",
            str(manifest_path),
            "--cutover-authorization-output",
            str(output_path),
            "--source-path",
            "prod://qualification/cutover-authorization/from-cli",
        ]
    )
    loaded = load_production_safety_qualification_cutover_authorization_report(
        output_path
    )

    assert exit_code == 0
    assert loaded.status == "cutover_authorization_recorded"
    assert loaded.cutover_authorization_recorded is True
    assert loaded.ready_for_human_cutover_review is True
    assert loaded.ready_for_production_cutover is False
    assert loaded.execution_allowed is False


def test_production_safety_qualification_cutover_release_handoff_records_without_execution(
    tmp_path,
) -> None:
    authorization = _recorded_cutover_authorization_report(
        tmp_path,
        omit_area="field_device_validator",
        source_path="prod://qualification/cutover-authorization/handoff-ready",
    )
    report = evaluate_production_safety_qualification_cutover_release_handoff(
        authorization,
        _cutover_release_handoff_manifest_payload(authorization),
        source_path="prod://qualification/cutover-release/handoff-report",
    )
    output_path = tmp_path / "cutover-release-handoff.json"
    stored = write_production_safety_qualification_cutover_release_handoff_report(
        report,
        output_path,
    )
    loaded = load_production_safety_qualification_cutover_release_handoff_report(
        output_path
    )

    assert report.status == "cutover_release_handoff_recorded"
    assert report.cutover_release_handoff_recorded is True
    assert report.ready_for_release_executor_handoff is True
    assert report.ready_for_production_cutover is False
    assert report.execution_allowed is False
    assert report.release_executor_ref == (
        "deployment://qualification/cutover-release/executor"
    )
    assert report.explicit_confirmation_phrase == (
        PRODUCTION_SAFETY_CUTOVER_RELEASE_HANDOFF_CONFIRMATION
    )
    assert stored == report
    assert loaded == report

    with pytest.raises(ValueError, match="cannot claim production cutover"):
        ProductionSafetyQualificationCutoverReleaseHandoffReport(
            **{
                **report.model_dump(mode="json"),
                "ready_for_production_cutover": True,
            }
        )


def test_production_safety_qualification_cutover_release_handoff_blocks_authorization(
    tmp_path,
) -> None:
    rerun = _ready_dossier_rerun_report(
        tmp_path,
        omit_area="transport_client",
        source_path="prod://qualification/dossier-rerun/handoff-blocked-auth",
    )
    authorization = evaluate_production_safety_qualification_cutover_authorization(
        rerun,
        _cutover_authorization_manifest_payload(rerun, omit_operator=True),
    )

    report = evaluate_production_safety_qualification_cutover_release_handoff(
        authorization,
        _cutover_release_handoff_manifest_payload(authorization),
    )

    assert report.status == "blocked_cutover_authorization_incomplete"
    assert report.cutover_release_handoff_recorded is False
    assert report.ready_for_release_executor_handoff is False
    assert report.ready_for_production_cutover is False
    assert "cutover_authorization_not_recorded" in report.blockers


def test_production_safety_qualification_cutover_release_handoff_blocks_request_gaps(
    tmp_path,
) -> None:
    authorization = _recorded_cutover_authorization_report(
        tmp_path,
        omit_area="phase1_writer_deployment",
        source_path="prod://qualification/cutover-authorization/handoff-gaps",
    )

    missing = evaluate_production_safety_qualification_cutover_release_handoff(
        authorization,
        _cutover_release_handoff_manifest_payload(
            authorization,
            include_request=False,
        ),
    )
    rejected = evaluate_production_safety_qualification_cutover_release_handoff(
        authorization,
        _cutover_release_handoff_manifest_payload(
            authorization,
            release_handoff_requested=False,
        ),
    )
    no_confirmation = evaluate_production_safety_qualification_cutover_release_handoff(
        authorization,
        _cutover_release_handoff_manifest_payload(
            authorization,
            operator_confirmation=False,
        ),
    )
    missing_executor = evaluate_production_safety_qualification_cutover_release_handoff(
        authorization,
        _cutover_release_handoff_manifest_payload(
            authorization,
            omit_release_executor=True,
        ),
    )
    mismatched = evaluate_production_safety_qualification_cutover_release_handoff(
        authorization,
        _cutover_release_handoff_manifest_payload(
            authorization,
            wrong_operator=True,
        ),
    )
    stale_request = evaluate_production_safety_qualification_cutover_release_handoff(
        authorization,
        _cutover_release_handoff_manifest_payload(
            authorization,
            requested_after_reference=True,
        ),
    )
    phrase_mismatch = evaluate_production_safety_qualification_cutover_release_handoff(
        authorization,
        _cutover_release_handoff_manifest_payload(
            authorization,
            confirmation_phrase="REQUEST SCOUT PRODUCTION CUTOVER",
        ),
    )

    assert missing.status == "missing_cutover_release_request"
    assert "cutover_release_request_missing" in missing.blockers
    assert rejected.status == "rejected_cutover_release_request"
    assert "cutover_release_handoff_not_requested" in rejected.blockers
    assert no_confirmation.status == "missing_operator_confirmation"
    assert "operator_confirmation_missing" in no_confirmation.blockers
    assert missing_executor.status == "missing_cutover_release_request"
    assert "release_executor_ref_missing" in missing_executor.blockers
    assert mismatched.status == "mismatched_cutover_release_request"
    assert "operator_identity_ref_mismatch" in mismatched.blockers
    assert stale_request.status == "mismatched_cutover_release_request"
    assert "requested_at_after_reference_time" in stale_request.blockers
    assert phrase_mismatch.status == "mismatched_cutover_release_request"
    assert "explicit_confirmation_phrase_mismatch" in phrase_mismatch.blockers


def test_production_safety_qualification_cutover_release_handoff_cli_writes_report(
    tmp_path,
) -> None:
    authorization = _recorded_cutover_authorization_report(
        tmp_path,
        omit_area="pi_hardware",
        source_path="prod://qualification/cutover-authorization/handoff-cli",
    )
    authorization_path = tmp_path / "cutover-authorization.json"
    manifest_path = tmp_path / "cutover-release-handoff-manifest.json"
    output_path = tmp_path / "cutover-release-handoff-report.json"
    write_production_safety_qualification_cutover_authorization_report(
        authorization,
        authorization_path,
    )
    manifest_path.write_text(
        json.dumps(_cutover_release_handoff_manifest_payload(authorization)),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "--cutover-release-authorization-report",
            str(authorization_path),
            "--cutover-release-handoff-manifest",
            str(manifest_path),
            "--cutover-release-handoff-output",
            str(output_path),
            "--source-path",
            "prod://qualification/cutover-release/handoff-from-cli",
        ]
    )
    loaded = load_production_safety_qualification_cutover_release_handoff_report(
        output_path
    )

    assert exit_code == 0
    assert loaded.status == "cutover_release_handoff_recorded"
    assert loaded.cutover_release_handoff_recorded is True
    assert loaded.ready_for_release_executor_handoff is True
    assert loaded.ready_for_production_cutover is False
    assert loaded.execution_allowed is False


def test_production_safety_qualification_cutover_release_effect_records_receipt_without_cutover(
    tmp_path,
) -> None:
    handoff = _recorded_cutover_release_handoff_report(
        tmp_path,
        omit_area="field_device_validator",
        source_path="prod://qualification/cutover-release/effect-handoff-ready",
    )
    report = evaluate_production_safety_qualification_cutover_release_effect_intake(
        handoff,
        _cutover_release_effect_manifest_payload(handoff),
        source_path="prod://qualification/cutover-release/effect-report",
    )
    output_path = tmp_path / "cutover-release-effect.json"
    stored = write_production_safety_qualification_cutover_release_effect_report(
        report,
        output_path,
    )
    loaded = load_production_safety_qualification_cutover_release_effect_report(
        output_path
    )

    assert report.status == "cutover_release_effect_receipt_recorded"
    assert report.cutover_release_effect_receipt_recorded is True
    assert report.ready_for_release_closure is True
    assert report.ready_for_production_cutover is False
    assert report.execution_allowed is False
    assert report.receipt_accepted is True
    assert report.executor_reported_release_completed is True
    assert report.source_integrity_evidence_present is True
    assert report.max_age_metadata_present is True
    assert report.release_execution_ref == (
        "deployment://qualification/cutover-release/execution"
    )
    assert report.release_result_ref == "prod://qualification/cutover-release/result"
    assert stored == report
    assert loaded == report

    with pytest.raises(ValueError, match="cannot claim production cutover"):
        ProductionSafetyQualificationCutoverReleaseEffectReport(
            **{
                **report.model_dump(mode="json"),
                "ready_for_production_cutover": True,
            }
        )


def test_production_safety_qualification_cutover_release_effect_blocks_handoff(
    tmp_path,
) -> None:
    rerun = _ready_dossier_rerun_report(
        tmp_path,
        omit_area="transport_client",
        source_path="prod://qualification/dossier-rerun/effect-blocked-handoff",
    )
    authorization = evaluate_production_safety_qualification_cutover_authorization(
        rerun,
        _cutover_authorization_manifest_payload(rerun, omit_operator=True),
    )
    handoff = evaluate_production_safety_qualification_cutover_release_handoff(
        authorization,
        _cutover_release_handoff_manifest_payload(authorization),
    )

    report = evaluate_production_safety_qualification_cutover_release_effect_intake(
        handoff,
        _cutover_release_effect_manifest_payload(handoff),
    )

    assert report.status == "blocked_cutover_release_handoff_incomplete"
    assert report.cutover_release_effect_receipt_recorded is False
    assert report.ready_for_release_closure is False
    assert report.ready_for_production_cutover is False
    assert "cutover_release_handoff_not_recorded" in report.blockers


def test_production_safety_qualification_cutover_release_effect_blocks_receipt_gaps(
    tmp_path,
) -> None:
    handoff = _recorded_cutover_release_handoff_report(
        tmp_path,
        omit_area="phase1_writer_deployment",
        source_path="prod://qualification/cutover-release/effect-gaps",
    )

    missing = evaluate_production_safety_qualification_cutover_release_effect_intake(
        handoff,
        _cutover_release_effect_manifest_payload(handoff, include_receipt=False),
    )
    rejected = evaluate_production_safety_qualification_cutover_release_effect_intake(
        handoff,
        _cutover_release_effect_manifest_payload(handoff, accepted=False),
    )
    unverified = evaluate_production_safety_qualification_cutover_release_effect_intake(
        handoff,
        _cutover_release_effect_manifest_payload(handoff, source_integrity=False),
    )
    missing_max_age = (
        evaluate_production_safety_qualification_cutover_release_effect_intake(
            handoff,
            _cutover_release_effect_manifest_payload(handoff, max_age=False),
        )
    )
    missing_execution = (
        evaluate_production_safety_qualification_cutover_release_effect_intake(
            handoff,
            _cutover_release_effect_manifest_payload(handoff, omit_execution=True),
        )
    )
    mismatched = evaluate_production_safety_qualification_cutover_release_effect_intake(
        handoff,
        _cutover_release_effect_manifest_payload(handoff, wrong_executor=True),
    )
    stale = evaluate_production_safety_qualification_cutover_release_effect_intake(
        handoff,
        _cutover_release_effect_manifest_payload(handoff, observed_after_reference=True),
    )
    incomplete = evaluate_production_safety_qualification_cutover_release_effect_intake(
        handoff,
        _cutover_release_effect_manifest_payload(handoff, completed=False),
    )

    assert missing.status == "missing_cutover_release_effect_receipt"
    assert "cutover_release_effect_receipt_missing" in missing.blockers
    assert rejected.status == "rejected_cutover_release_effect_receipt"
    assert "cutover_release_effect_receipt_rejected" in rejected.blockers
    assert unverified.status == "unverified_cutover_release_effect_source"
    assert "source_integrity_evidence_missing" in unverified.blockers
    assert missing_max_age.status == "unverified_cutover_release_effect_source"
    assert "max_age_metadata_missing" in missing_max_age.blockers
    assert missing_execution.status == "mismatched_cutover_release_effect_receipt"
    assert "release_execution_ref_missing" in missing_execution.blockers
    assert mismatched.status == "mismatched_cutover_release_effect_receipt"
    assert "release_executor_ref_mismatch" in mismatched.blockers
    assert stale.status == "mismatched_cutover_release_effect_receipt"
    assert "release_observed_at_after_reference_time" in stale.blockers
    assert incomplete.status == "mismatched_cutover_release_effect_receipt"
    assert "release_effect_not_completed" in incomplete.blockers


def test_production_safety_qualification_cutover_release_effect_cli_writes_report(
    tmp_path,
) -> None:
    handoff = _recorded_cutover_release_handoff_report(
        tmp_path,
        omit_area="pi_hardware",
        source_path="prod://qualification/cutover-release/effect-cli-handoff",
    )
    handoff_path = tmp_path / "cutover-release-handoff.json"
    manifest_path = tmp_path / "cutover-release-effect-manifest.json"
    output_path = tmp_path / "cutover-release-effect-report.json"
    write_production_safety_qualification_cutover_release_handoff_report(
        handoff,
        handoff_path,
    )
    manifest_path.write_text(
        json.dumps(_cutover_release_effect_manifest_payload(handoff)),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "--cutover-release-effect-handoff-report",
            str(handoff_path),
            "--cutover-release-effect-manifest",
            str(manifest_path),
            "--cutover-release-effect-output",
            str(output_path),
            "--source-path",
            "prod://qualification/cutover-release/effect-from-cli",
        ]
    )
    loaded = load_production_safety_qualification_cutover_release_effect_report(
        output_path
    )

    assert exit_code == 0
    assert loaded.status == "cutover_release_effect_receipt_recorded"
    assert loaded.cutover_release_effect_receipt_recorded is True
    assert loaded.ready_for_release_closure is True
    assert loaded.ready_for_production_cutover is False
    assert loaded.execution_allowed is False


def test_production_safety_qualification_cutover_release_closure_records_review_without_cutover(
    tmp_path,
) -> None:
    effect = _recorded_cutover_release_effect_report(
        tmp_path,
        omit_area="field_device_validator",
        source_path="prod://qualification/cutover-release/closure-effect-ready",
    )
    report = evaluate_production_safety_qualification_cutover_release_closure(
        effect,
        _cutover_release_closure_manifest_payload(effect),
        source_path="prod://qualification/cutover-release/closure-report",
    )
    output_path = tmp_path / "cutover-release-closure.json"
    stored = write_production_safety_qualification_cutover_release_closure_report(
        report,
        output_path,
    )
    loaded = load_production_safety_qualification_cutover_release_closure_report(
        output_path
    )

    assert report.status == "cutover_release_closure_recorded"
    assert report.cutover_release_closure_recorded is True
    assert report.ready_for_production_cutover_review is True
    assert report.ready_for_production_cutover is False
    assert report.execution_allowed is False
    assert report.review_accepted is True
    assert report.closure_reviewer_confirmation is True
    assert report.source_integrity_evidence_present is True
    assert report.max_age_metadata_present is True
    assert report.release_result_ref == effect.release_result_ref
    assert report.rollback_plan_ref == (
        effect.cutover_release_handoff_report.rollback_plan_ref
    )
    assert stored == report
    assert loaded == report

    with pytest.raises(ValueError, match="cannot claim production cutover"):
        ProductionSafetyQualificationCutoverReleaseClosureReport(
            **{
                **report.model_dump(mode="json"),
                "ready_for_production_cutover": True,
            }
        )


def test_production_safety_qualification_cutover_release_closure_blocks_effect(
    tmp_path,
) -> None:
    handoff = _recorded_cutover_release_handoff_report(
        tmp_path,
        omit_area="transport_client",
        source_path="prod://qualification/cutover-release/closure-blocked-handoff",
    )
    effect = evaluate_production_safety_qualification_cutover_release_effect_intake(
        handoff,
        _cutover_release_effect_manifest_payload(handoff, include_receipt=False),
    )

    report = evaluate_production_safety_qualification_cutover_release_closure(
        effect,
        _cutover_release_closure_manifest_payload(effect),
    )

    assert report.status == "blocked_cutover_release_effect_incomplete"
    assert report.cutover_release_closure_recorded is False
    assert report.ready_for_production_cutover_review is False
    assert report.ready_for_production_cutover is False
    assert "cutover_release_effect_not_recorded" in report.blockers


def test_production_safety_qualification_cutover_release_closure_blocks_review_gaps(
    tmp_path,
) -> None:
    effect = _recorded_cutover_release_effect_report(
        tmp_path,
        omit_area="phase1_writer_deployment",
        source_path="prod://qualification/cutover-release/closure-gaps",
    )

    missing = evaluate_production_safety_qualification_cutover_release_closure(
        effect,
        _cutover_release_closure_manifest_payload(effect, include_review=False),
    )
    rejected = evaluate_production_safety_qualification_cutover_release_closure(
        effect,
        _cutover_release_closure_manifest_payload(effect, accepted=False),
    )
    unverified = evaluate_production_safety_qualification_cutover_release_closure(
        effect,
        _cutover_release_closure_manifest_payload(effect, source_integrity=False),
    )
    missing_confirmation = (
        evaluate_production_safety_qualification_cutover_release_closure(
            effect,
            _cutover_release_closure_manifest_payload(effect, confirmation=False),
        )
    )
    wrong_phrase = evaluate_production_safety_qualification_cutover_release_closure(
        effect,
        _cutover_release_closure_manifest_payload(effect, wrong_phrase=True),
    )
    mismatched = evaluate_production_safety_qualification_cutover_release_closure(
        effect,
        _cutover_release_closure_manifest_payload(effect, wrong_result=True),
    )
    stale = evaluate_production_safety_qualification_cutover_release_closure(
        effect,
        _cutover_release_closure_manifest_payload(effect, reviewed_after_reference=True),
    )
    expired = evaluate_production_safety_qualification_cutover_release_closure(
        effect,
        _cutover_release_closure_manifest_payload(effect, expired=True),
    )

    assert missing.status == "missing_cutover_release_closure_review"
    assert "cutover_release_closure_review_missing" in missing.blockers
    assert rejected.status == "rejected_cutover_release_closure_review"
    assert "cutover_release_closure_review_rejected" in rejected.blockers
    assert unverified.status == "unverified_cutover_release_closure_source"
    assert "source_integrity_evidence_missing" in unverified.blockers
    assert missing_confirmation.status == "missing_release_closure_confirmation"
    assert "closure_reviewer_confirmation_missing" in missing_confirmation.blockers
    assert wrong_phrase.status == "missing_release_closure_confirmation"
    assert "explicit_confirmation_phrase_mismatch" in wrong_phrase.blockers
    assert mismatched.status == "mismatched_cutover_release_closure_review"
    assert "release_result_ref_mismatch" in mismatched.blockers
    assert stale.status == "mismatched_cutover_release_closure_review"
    assert "closure_reviewed_at_after_reference_time" in stale.blockers
    assert expired.status == "expired_cutover_release_closure_review"
    assert "expires_at_at_or_before_reference_time" in expired.blockers


def test_production_safety_qualification_cutover_release_closure_cli_writes_report(
    tmp_path,
) -> None:
    effect = _recorded_cutover_release_effect_report(
        tmp_path,
        omit_area="pi_hardware",
        source_path="prod://qualification/cutover-release/closure-cli-effect",
    )
    effect_path = tmp_path / "cutover-release-effect.json"
    manifest_path = tmp_path / "cutover-release-closure-manifest.json"
    output_path = tmp_path / "cutover-release-closure-report.json"
    write_production_safety_qualification_cutover_release_effect_report(
        effect,
        effect_path,
    )
    manifest_path.write_text(
        json.dumps(_cutover_release_closure_manifest_payload(effect)),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "--cutover-release-closure-effect-report",
            str(effect_path),
            "--cutover-release-closure-manifest",
            str(manifest_path),
            "--cutover-release-closure-output",
            str(output_path),
            "--source-path",
            "prod://qualification/cutover-release/closure-from-cli",
        ]
    )
    loaded = load_production_safety_qualification_cutover_release_closure_report(
        output_path
    )

    assert exit_code == 0
    assert loaded.status == "cutover_release_closure_recorded"
    assert loaded.cutover_release_closure_recorded is True
    assert loaded.ready_for_production_cutover_review is True
    assert loaded.ready_for_production_cutover is False
    assert loaded.execution_allowed is False
