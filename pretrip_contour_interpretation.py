from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ContourInterpretationMode(StrEnum):
    MANUAL = "manual"
    AI_ASSISTED = "ai_assisted"


class ContourCandidateOrigin(StrEnum):
    MANUAL_BASELINE = "manual_baseline"
    AI_ASSISTED_MODEL = "ai_assisted_model"


class ContourLifecycleStatus(StrEnum):
    ADMIN_REVIEW_PENDING = "admin_review_pending"
    ACCEPTED_AFTER_HUMAN_REVIEW = "accepted_after_human_review"
    REJECTED_AFTER_HUMAN_REVIEW = "rejected_after_human_review"
    CORRECTED_AFTER_HUMAN_REVIEW = "corrected_after_human_review"


class ContourReviewDecision(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    CORRECTED = "corrected"


class ContourSourceRefs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    image_artifact_ref: str
    dtm_coverage_summary_ref: str
    segment_dtm_coverage_ref: str | None = None


class ContourTargetRefs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    route_artifact_ref: str
    segment_candidate_refs: list[str] = Field(default_factory=list)
    checkpoint_candidate_refs: list[str] = Field(default_factory=list)


class ContourReviewLifecycle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lifecycle_status: ContourLifecycleStatus = ContourLifecycleStatus.ADMIN_REVIEW_PENDING
    review_decision: ContourReviewDecision | None = None
    human_review_ref: str | None = None
    corrected_candidate_ref: str | None = None

    @model_validator(mode="after")
    def _review_gate(self) -> ContourReviewLifecycle:
        if self.lifecycle_status == ContourLifecycleStatus.ADMIN_REVIEW_PENDING:
            if self.review_decision is not None or self.human_review_ref is not None:
                raise ValueError("pending contour candidates must not carry an accepted review decision")
            if self.corrected_candidate_ref is not None:
                raise ValueError("pending contour candidates must not carry correction refs")
            return self

        if self.human_review_ref is None:
            raise ValueError("accepted, rejected, or corrected contour candidates require HumanReview")
        if self.lifecycle_status == ContourLifecycleStatus.ACCEPTED_AFTER_HUMAN_REVIEW:
            if self.review_decision != ContourReviewDecision.ACCEPTED:
                raise ValueError("accepted lifecycle requires accepted review_decision")
        if self.lifecycle_status == ContourLifecycleStatus.REJECTED_AFTER_HUMAN_REVIEW:
            if self.review_decision != ContourReviewDecision.REJECTED:
                raise ValueError("rejected lifecycle requires rejected review_decision")
        if self.lifecycle_status == ContourLifecycleStatus.CORRECTED_AFTER_HUMAN_REVIEW:
            if self.review_decision != ContourReviewDecision.CORRECTED:
                raise ValueError("corrected lifecycle requires corrected review_decision")
            if self.corrected_candidate_ref is None:
                raise ValueError("corrected lifecycle requires corrected_candidate_ref")
        return self


class ContourInterpretationCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    status: Literal["candidate", "accepted", "rejected", "corrected"] = "candidate"
    interpretation_mode: ContourInterpretationMode
    candidate_origin: ContourCandidateOrigin
    review_lifecycle: ContourReviewLifecycle = Field(default_factory=ContourReviewLifecycle)
    source_artifact_refs: ContourSourceRefs
    target_refs: ContourTargetRefs
    contour_density_notes: list[str] = Field(default_factory=list)
    terrain_shape_notes: list[str] = Field(default_factory=list)
    confidence: Literal["low", "medium", "high", "unknown"] = "unknown"
    admin_review_required: bool = True
    human_review_required: bool = True
    accepted_planning_assumption_allowed: bool = False
    not_observed_fact: Literal[True] = True
    notes: str = ""

    @model_validator(mode="after")
    def _candidate_boundaries(self) -> ContourInterpretationCandidate:
        if self.source_artifact_refs.image_artifact_ref != "artifact.photo.g11_hiking":
            raise ValueError("contour interpretation candidates must reference G11_hiking photo artifact")
        if not self.source_artifact_refs.dtm_coverage_summary_ref:
            raise ValueError("DTM coverage summary ref is required")
        if not self.target_refs.segment_candidate_refs:
            raise ValueError("at least one target segment candidate ref is required")
        if self.interpretation_mode == ContourInterpretationMode.AI_ASSISTED:
            if self.candidate_origin != ContourCandidateOrigin.AI_ASSISTED_MODEL:
                raise ValueError("AI-assisted contour candidates must use ai_assisted_model origin")
            if not self.admin_review_required or not self.human_review_required:
                raise ValueError("AI-assisted contour candidates require admin HumanReview")
        if self.interpretation_mode == ContourInterpretationMode.MANUAL:
            if self.candidate_origin != ContourCandidateOrigin.MANUAL_BASELINE:
                raise ValueError("manual contour candidates must use manual_baseline origin")
        if self.status == "candidate":
            if self.review_lifecycle.lifecycle_status != ContourLifecycleStatus.ADMIN_REVIEW_PENDING:
                raise ValueError("candidate contour records must be pending admin review")
            if self.accepted_planning_assumption_allowed:
                raise ValueError("candidate contour records cannot be accepted planning assumptions")
        if self.status in {"accepted", "corrected"}:
            if self.review_lifecycle.human_review_ref is None:
                raise ValueError("accepted or corrected contour records require HumanReview")
            if not self.accepted_planning_assumption_allowed:
                raise ValueError("accepted or corrected contour records must explicitly allow planning assumptions")
        if self.status == "rejected" and self.accepted_planning_assumption_allowed:
            raise ValueError("rejected contour records cannot be accepted planning assumptions")
        return self


class ContourInterpretationCandidateSet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: str
    project_id: str
    status: Literal["candidate"] = "candidate"
    route_artifact_ref: str
    source_artifact_refs: list[str] = Field(default_factory=list)
    candidates: list[ContourInterpretationCandidate] = Field(default_factory=list)
    not_observed_fact: Literal[True] = True
    notes: str = ""

    @model_validator(mode="after")
    def _set_boundaries(self) -> ContourInterpretationCandidateSet:
        if "artifact.photo.g11_hiking" not in self.source_artifact_refs:
            raise ValueError("candidate set must include artifact.photo.g11_hiking")
        if any(candidate.status != "candidate" for candidate in self.candidates):
            raise ValueError("contour interpretation records are candidate-only")
        return self


def load_contour_interpretation_candidate_set(
    path: Path | str,
) -> ContourInterpretationCandidateSet:
    return ContourInterpretationCandidateSet.model_validate(json.loads(Path(path).read_text()))
