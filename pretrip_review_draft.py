from __future__ import annotations

from datetime import datetime
from typing import Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


ReviewDraftStatus = Literal["accepted", "rejected", "corrected", "needs_info"]
CorrectionScalar: TypeAlias = str | int | float | bool | None

FORBIDDEN_RAW_PAYLOAD_FRAGMENTS = (
    "raw_payload",
    "raw_payload_fragment",
    "payload_fragment",
    "source_payload",
    "raw_samples",
    "incident_samples",
    "<trkpt",
    '"coordinates"',
    "coordinates",
    "catographydata",
    "PdrSample",
    ".gpx",
    ".grd",
    ".hdr",
    ".jpg",
    ".jpeg",
    ".tif",
    ".tiff",
    "/safety",
    "Phase1IncidentBridge",
    "SCOUT_PHASE2_INCIDENT_BRIDGE",
)


class StrictReviewDraftModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ReviewQueueItemRef(StrictReviewDraftModel):
    review_queue_manifest_id: str
    item_id: str
    source_ref: str
    candidate_ref: str


class ReviewCorrectionPayload(StrictReviewDraftModel):
    summary: str = ""
    field_updates: dict[str, CorrectionScalar] = Field(default_factory=dict)
    replacement_ref_ids: tuple[str, ...] = Field(default_factory=tuple)
    reviewer_notes: str = ""

    @model_validator(mode="after")
    def enforce_structured_correction(self) -> "ReviewCorrectionPayload":
        if not self.summary and not self.field_updates and not self.replacement_ref_ids:
            raise ValueError("correction payload requires summary, field_updates, or replacement_ref_ids")
        _assert_no_raw_payload_fragments(self.model_dump(mode="json"))
        return self


class PreTripReviewDraftAction(StrictReviewDraftModel):
    draft_action_id: str
    status: ReviewDraftStatus
    target_ids: tuple[str, ...] = Field(min_length=1)
    source_review_queue_item_refs: tuple[ReviewQueueItemRef, ...] = Field(min_length=1)
    correction_payload: ReviewCorrectionPayload | None = None
    reviewer_alias: str
    created_at: str
    draft_only: Literal[True] = True
    mutates_source_package: Literal[False] = False
    compiles_mission_graph: Literal[False] = False
    phase1_runtime_mutation_allowed: Literal[False] = False

    @field_validator("created_at")
    @classmethod
    def require_iso_created_at(cls, value: str) -> str:
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("created_at must be an ISO-8601 datetime") from exc
        return value

    @model_validator(mode="after")
    def enforce_draft_boundary(self) -> "PreTripReviewDraftAction":
        if self.status == "corrected" and self.correction_payload is None:
            raise ValueError("corrected draft action requires correction_payload")
        if self.status != "corrected" and self.correction_payload is not None:
            raise ValueError("correction_payload is only allowed for corrected draft actions")
        _assert_no_raw_payload_fragments(self.model_dump(mode="json"))
        return self


class PreTripReviewDraftLog(StrictReviewDraftModel):
    log_id: str
    artifact_kind: Literal["pretrip_review_draft_log"] = "pretrip_review_draft_log"
    actions: tuple[PreTripReviewDraftAction, ...] = Field(default_factory=tuple)
    draft_only: Literal[True] = True
    mutates_source_package: Literal[False] = False
    compiles_mission_graph: Literal[False] = False
    phase1_runtime_mutation_allowed: Literal[False] = False

    @model_validator(mode="after")
    def enforce_log_boundary(self) -> "PreTripReviewDraftLog":
        _assert_no_raw_payload_fragments(self.model_dump(mode="json"))
        return self

    def append(self, action: PreTripReviewDraftAction) -> "PreTripReviewDraftLog":
        return self.model_copy(update={"actions": (*self.actions, action)})


def build_pretrip_review_draft_log(
    actions: tuple[PreTripReviewDraftAction, ...] | list[PreTripReviewDraftAction],
    *,
    log_id: str,
) -> PreTripReviewDraftLog:
    log = PreTripReviewDraftLog(log_id=log_id)
    for action in actions:
        log = log.append(action)
    return log


def _assert_no_raw_payload_fragments(value: object) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            _reject_raw_payload_fragment(str(key))
            _assert_no_raw_payload_fragments(item)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _assert_no_raw_payload_fragments(item)
        return
    if isinstance(value, str):
        _reject_raw_payload_fragment(value)


def _reject_raw_payload_fragment(value: str) -> None:
    lowered = value.lower()
    for fragment in FORBIDDEN_RAW_PAYLOAD_FRAGMENTS:
        if fragment.lower() in lowered:
            raise ValueError(f"forbidden raw payload fragment: {fragment}")
