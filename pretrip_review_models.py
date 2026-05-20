from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


PreTripReviewRefKind = Literal[
    "checkpoint",
    "segment",
    "retreat_route",
    "map_candidate",
    "route_guide_timing",
    "planning_reference",
    "package",
]

PreTripReviewDecision = Literal["accepted", "rejected", "corrected", "noted"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PreTripCorrection(StrictModel):
    payload: dict[str, Any] = Field(default_factory=dict)
    refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_payload_or_refs(self) -> PreTripCorrection:
        if not self.payload and not self.refs:
            raise ValueError("correction requires payload or refs")
        return self


class PreTripHumanReview(StrictModel):
    review_id: str
    reviewer_id: str
    reviewed_ref: str
    reviewed_ref_kind: PreTripReviewRefKind
    reviewed_at: str
    decision: PreTripReviewDecision
    notes: str = ""
    correction: PreTripCorrection | None = None
    source_candidate_snapshot_hash: str | None = None
    source_candidate_artifact_ref: str | None = None

    @model_validator(mode="after")
    def require_source_snapshot_pointer(self) -> PreTripHumanReview:
        if not self.source_candidate_snapshot_hash and not self.source_candidate_artifact_ref:
            raise ValueError("review requires source_candidate_snapshot_hash or source_candidate_artifact_ref")
        if self.decision == "corrected" and self.correction is None:
            raise ValueError("corrected review requires correction")
        return self


class PreTripHumanReviewLog(StrictModel):
    log_id: str
    reviews: tuple[PreTripHumanReview, ...] = Field(default_factory=tuple)

    def append(self, review: PreTripHumanReview) -> PreTripHumanReviewLog:
        return self.model_copy(update={"reviews": (*self.reviews, review)})

    def index_by_reviewed_ref(self) -> dict[str, list[PreTripHumanReview]]:
        return index_reviews_by_reviewed_ref(self.reviews)

    def latest_review_for(self, reviewed_ref: str) -> PreTripHumanReview | None:
        return latest_review_for(self.reviews, reviewed_ref)


def index_reviews_by_reviewed_ref(
    reviews: Iterable[PreTripHumanReview],
) -> dict[str, list[PreTripHumanReview]]:
    indexed: dict[str, list[PreTripHumanReview]] = {}
    for review in reviews:
        indexed.setdefault(review.reviewed_ref, []).append(review)
    return indexed


def latest_review_for(
    reviews: Iterable[PreTripHumanReview],
    reviewed_ref: str,
) -> PreTripHumanReview | None:
    latest: PreTripHumanReview | None = None
    for review in reviews:
        if review.reviewed_ref == reviewed_ref:
            latest = review
    return latest


def source_candidate_snapshot_hash(source_candidate: BaseModel | Mapping[str, Any]) -> str:
    payload = _snapshot_payload(source_candidate)
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _snapshot_payload(source_candidate: BaseModel | Mapping[str, Any]) -> Any:
    if isinstance(source_candidate, BaseModel):
        return source_candidate.model_dump(mode="json")
    return json.loads(json.dumps(source_candidate, sort_keys=True, ensure_ascii=True))
