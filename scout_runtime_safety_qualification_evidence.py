from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scout_energy_models import sha256_file
from scout_runtime_safety_production_qualification import (
    PRODUCTION_SAFETY_QUALIFICATION_REQUIRED_CLAIMS,
    ProductionSafetyQualificationArea,
    ProductionSafetyQualificationClaimId,
    ProductionSafetyQualificationEvidenceArtifact,
    ProductionSafetyQualificationEvidenceBundle,
    ProductionSafetyQualificationEvidenceClaim,
    ProductionSafetyQualificationEvidencePackage,
)


_SENSITIVE_SUMMARY_MARKERS = (
    "api_key=",
    "authorization=",
    "password=",
    "token=",
    "-----begin",
)


class ProductionQualificationClaimSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: ProductionSafetyQualificationClaimId
    source_artifact_refs: list[str] = Field(min_length=1)
    source_artifact_sha256s: list[str] = Field(min_length=1)
    observed_at: datetime
    verified: bool
    summary: str = Field(min_length=1, max_length=240)
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_claim_source(self) -> "ProductionQualificationClaimSource":
        if len(self.source_artifact_refs) != len(self.source_artifact_sha256s):
            raise ValueError("source artifact refs and sha256s must have equal length")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("claim observation time must be timezone-aware")
        normalized_summary = self.summary.casefold()
        if any(marker in normalized_summary for marker in _SENSITIVE_SUMMARY_MARKERS):
            raise ValueError("claim summary may not contain credential-like material")
        return self


class ProductionQualificationAreaEvidenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    area: ProductionSafetyQualificationArea
    source_provider: str = Field(min_length=1)
    source_path: str = Field(min_length=1)
    reference_time: datetime
    qualification_ref: str = Field(min_length=1)
    qualification_sha256: str = Field(min_length=1)
    reviewed_effect_boundary_ref: str = Field(min_length=1)
    reviewed_effect_boundary_sha256: str = Field(min_length=1)
    operator_review_ref: str = Field(min_length=1)
    operator_review_sha256: str = Field(min_length=1)
    reviewer_observed_at: datetime
    max_age_seconds: int = Field(gt=0)
    claims: list[ProductionQualificationClaimSource] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_area_request(self) -> "ProductionQualificationAreaEvidenceRequest":
        if self.reference_time.tzinfo is None or self.reference_time.utcoffset() is None:
            raise ValueError("reference_time must be timezone-aware")
        if (
            self.reviewer_observed_at.tzinfo is None
            or self.reviewer_observed_at.utcoffset() is None
        ):
            raise ValueError("reviewer_observed_at must be timezone-aware")
        claim_ids = [claim.claim_id for claim in self.claims]
        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError("qualification claim ids must be unique")
        allowed_claims = set(PRODUCTION_SAFETY_QUALIFICATION_REQUIRED_CLAIMS[self.area])
        unexpected = sorted(set(claim_ids) - allowed_claims)
        if unexpected:
            raise ValueError(f"unexpected qualification claims: {unexpected}")
        if any(claim.observed_at > self.reviewer_observed_at for claim in self.claims):
            raise ValueError("review cannot predate claim evidence")
        if self.reviewer_observed_at > self.reference_time:
            raise ValueError("review cannot be after reference_time")
        return self


class ProductionQualificationAreaEvidencePaths(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    area: ProductionSafetyQualificationArea
    bundle_path: Path
    source_package_path: Path
    claim_artifact_paths: list[Path]


def write_production_qualification_area_evidence(
    request: ProductionQualificationAreaEvidenceRequest,
    root_path: str | Path,
) -> ProductionQualificationAreaEvidencePaths:
    root = Path(root_path)
    area_dir = root / request.area
    claim_dir = area_dir / "claims"
    claim_dir.mkdir(parents=True, exist_ok=True)

    bundle_claims: list[ProductionSafetyQualificationEvidenceClaim] = []
    package_artifacts: list[ProductionSafetyQualificationEvidenceArtifact] = []
    claim_paths: list[Path] = []
    for claim_source in request.claims:
        claim_ref = f"{request.source_path}/claims/{claim_source.claim_id}"
        claim_path = claim_dir / f"{claim_source.claim_id}.json"
        claim_payload = {
            "artifact_kind": "scout_production_qualification_sanitized_claim_evidence",
            "artifact_version": "production_qualification_sanitized_claim_evidence.v0",
            "area": request.area,
            "claim_id": claim_source.claim_id,
            "source_artifact_refs": claim_source.source_artifact_refs,
            "source_artifact_sha256s": claim_source.source_artifact_sha256s,
            "observed_at": claim_source.observed_at.isoformat(),
            "verified": claim_source.verified,
            "summary": claim_source.summary,
            "sanitized": True,
            "credential_material_present": False,
            "raw_payload_present": False,
            "safety_api_path_present": False,
            "runtime_safety_truth_present": False,
            "notes": claim_source.notes,
        }
        claim_path.write_text(
            json.dumps(claim_payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        claim_sha256 = sha256_file(claim_path)
        claim_paths.append(claim_path)
        bundle_claims.append(
            ProductionSafetyQualificationEvidenceClaim(
                claim_id=claim_source.claim_id,
                evidence_ref=claim_ref,
                evidence_sha256=claim_sha256,
                evidence_observed_at=claim_source.observed_at,
                reviewer_ref=request.operator_review_ref,
                reviewer_sha256=request.operator_review_sha256,
                reviewer_observed_at=request.reviewer_observed_at,
                max_age_seconds=request.max_age_seconds,
                accepted=claim_source.verified,
                notes=claim_source.notes,
            )
        )
        package_artifacts.append(
            ProductionSafetyQualificationEvidenceArtifact(
                evidence_ref=claim_ref,
                evidence_sha256=claim_sha256,
                local_path=claim_path.relative_to(root).as_posix(),
                redacted_or_sanitized=True,
            )
        )

    bundle = ProductionSafetyQualificationEvidenceBundle(
        area=request.area,
        source_provider=request.source_provider,
        source_path=request.source_path,
        reference_time=request.reference_time,
        qualification_ref=request.qualification_ref,
        qualification_sha256=request.qualification_sha256,
        reviewed_effect_boundary_ref=request.reviewed_effect_boundary_ref,
        reviewed_effect_boundary_sha256=request.reviewed_effect_boundary_sha256,
        operator_review_ref=request.operator_review_ref,
        operator_review_sha256=request.operator_review_sha256,
        claims=bundle_claims,
        credential_material_embedded=False,
        raw_payload_embedded=False,
        notes=[
            "Generated from sanitized source receipts; admission performs no external effects.",
            *request.notes,
        ],
    )
    source_package = ProductionSafetyQualificationEvidencePackage(
        area=request.area,
        source_provider=request.source_provider,
        source_path=f"{request.source_path}/source-package",
        artifacts=package_artifacts,
    )
    bundle_path = area_dir / "bundle.json"
    source_package_path = area_dir / "source-package.json"
    bundle_path.write_text(bundle.model_dump_json(indent=2) + "\n", encoding="utf-8")
    source_package_path.write_text(
        source_package.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    return ProductionQualificationAreaEvidencePaths(
        area=request.area,
        bundle_path=bundle_path,
        source_package_path=source_package_path,
        claim_artifact_paths=claim_paths,
    )
