from __future__ import annotations

import json
from datetime import datetime, timezone

from scout_runtime_safety_production_qualification import (
    PRODUCTION_SAFETY_QUALIFICATION_REQUIRED_CLAIMS,
    evaluate_production_safety_qualification_bundle,
    verify_production_safety_qualification_source_integrity,
)
from scout_runtime_safety_qualification_evidence import (
    ProductionQualificationAreaEvidenceRequest,
    ProductionQualificationClaimSource,
    write_production_qualification_area_evidence,
)


def _request(
    *,
    rejected_claim: str | None = None,
) -> ProductionQualificationAreaEvidenceRequest:
    observed_at = datetime(2026, 8, 31, 3, 0, tzinfo=timezone.utc)
    reviewed_at = datetime(2026, 8, 31, 3, 5, tzinfo=timezone.utc)
    claims = []
    for claim_id in PRODUCTION_SAFETY_QUALIFICATION_REQUIRED_CLAIMS[
        "live_provider_api"
    ]:
        claims.append(
            ProductionQualificationClaimSource(
                claim_id=claim_id,
                source_artifact_refs=[
                    "prod://qualification/cwa/live-run-001/report"
                ],
                source_artifact_sha256s=["a" * 64],
                observed_at=observed_at,
                verified=claim_id != rejected_claim,
                summary=f"Sanitized evidence for {claim_id}",
            )
        )
    return ProductionQualificationAreaEvidenceRequest(
        area="live_provider_api",
        source_provider="scout_runtime_safety_live_qualification",
        source_path="prod://qualification/cwa/live-run-001/area/live-provider-api",
        reference_time=reviewed_at,
        qualification_ref="prod://qualification/cwa/live-run-001/report",
        qualification_sha256="a" * 64,
        reviewed_effect_boundary_ref=(
            "attestation://qualification/cwa/live-provider-api/boundary"
        ),
        reviewed_effect_boundary_sha256="b" * 64,
        operator_review_ref="operator://qualification/scout-owner/cwa-live-review",
        operator_review_sha256="c" * 64,
        reviewer_observed_at=reviewed_at,
        max_age_seconds=3600,
        claims=claims,
    )


def test_area_evidence_writer_produces_source_verified_qualification_receipt(
    tmp_path,
) -> None:
    paths = write_production_qualification_area_evidence(_request(), tmp_path)
    bundle = json.loads(paths.bundle_path.read_text(encoding="utf-8"))
    source_package = json.loads(
        paths.source_package_path.read_text(encoding="utf-8")
    )
    integrity = verify_production_safety_qualification_source_integrity(
        bundle,
        source_package,
        root_path=tmp_path,
        source_path=(
            "prod://qualification/cwa/live-run-001/area/live-provider-api/"
            "source-integrity"
        ),
    )
    decision = evaluate_production_safety_qualification_bundle(
        bundle,
        source_integrity_report=integrity,
    )

    assert decision.status == "qualification_receipt_accepted"
    assert decision.ready_for_cutover_receipt is True
    assert decision.receipt.status == "qualified"
    assert integrity.status == "source_integrity_verified"
    assert paths.claim_artifact_paths
    serialized = paths.bundle_path.read_text(encoding="utf-8")
    assert "credential_material_embedded" in serialized
    assert '"credential_material_embedded": false' in serialized
    assert '"raw_payload_embedded": false' in serialized


def test_area_evidence_writer_preserves_rejected_claim_as_blocker(tmp_path) -> None:
    paths = write_production_qualification_area_evidence(
        _request(rejected_claim="provider_response_sanitized"),
        tmp_path,
    )
    bundle = json.loads(paths.bundle_path.read_text(encoding="utf-8"))
    source_package = json.loads(
        paths.source_package_path.read_text(encoding="utf-8")
    )
    integrity = verify_production_safety_qualification_source_integrity(
        bundle,
        source_package,
        root_path=tmp_path,
        source_path=(
            "prod://qualification/cwa/live-run-001/area/live-provider-api/"
            "source-integrity"
        ),
    )
    decision = evaluate_production_safety_qualification_bundle(
        bundle,
        source_integrity_report=integrity,
    )

    assert decision.status == "blocked_rejected_required_claims"
    assert decision.ready_for_cutover_receipt is False
    assert decision.rejected_claims == ["provider_response_sanitized"]


def test_area_evidence_request_rejects_duplicate_claims() -> None:
    request = _request()
    duplicate = request.claims[0]

    try:
        ProductionQualificationAreaEvidenceRequest(
            **{
                **request.model_dump(),
                "claims": [*request.claims, duplicate],
            }
        )
    except ValueError as exc:
        assert "claim ids must be unique" in str(exc)
    else:
        raise AssertionError("duplicate qualification claims must be rejected")
