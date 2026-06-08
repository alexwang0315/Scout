from __future__ import annotations

import json
from collections import Counter
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from pretrip_review_draft_fixture import DEFAULT_CHILAI_PROJECT_REF


class ReviewDecision(StrEnum):
    ACCEPTED = "accepted"
    CORRECTED = "corrected"
    REJECTED = "rejected"


class StrictDecisionLogModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceReviewQueueItemRef(StrictDecisionLogModel):
    review_queue_manifest_id: str
    item_id: str
    source_ref: str
    candidate_ref: str


class ReviewDecisionCorrection(StrictDecisionLogModel):
    summary: str
    field_updates: dict[str, Any] = Field(default_factory=dict)
    replacement_ref_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_structured_correction(self) -> "ReviewDecisionCorrection":
        if not self.summary and not self.field_updates and not self.replacement_ref_ids:
            raise ValueError("decision correction requires summary, field_updates, or replacement_ref_ids")
        _assert_no_raw_payload_fragments(self.model_dump(mode="json"))
        return self


class ReviewDecisionRecord(StrictDecisionLogModel):
    decision_id: str
    draft_action_id: str
    decision: ReviewDecision
    candidate_ref: str
    target_ids: list[str] = Field(min_length=1)
    source_review_queue_item_refs: list[SourceReviewQueueItemRef] = Field(min_length=1)
    reviewer_alias: str
    decided_at: str
    summary: str
    correction: ReviewDecisionCorrection | None = None
    append_only: Literal[True] = True
    source_mutation_allowed: Literal[False] = False
    package_mutation_allowed: Literal[False] = False
    runtime_mutation_allowed: Literal[False] = False
    phase1_runtime_mutation_allowed: Literal[False] = False
    phase2_writeback_allowed: Literal[False] = False
    compiles_mission_graph: Literal[False] = False
    raw_payloads_embedded: Literal[False] = False

    @field_validator("decided_at")
    @classmethod
    def require_iso_decided_at(cls, value: str) -> str:
        from datetime import datetime

        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("decided_at must be an ISO-8601 datetime") from exc
        return value

    @model_validator(mode="after")
    def enforce_decision_boundary(self) -> "ReviewDecisionRecord":
        if self.decision == ReviewDecision.CORRECTED and self.correction is None:
            raise ValueError("corrected decision requires correction")
        if self.decision != ReviewDecision.CORRECTED and self.correction is not None:
            raise ValueError("correction is only allowed for corrected decisions")
        _assert_no_raw_payload_fragments(self.model_dump(mode="json"))
        return self


class ReviewDecisionCounts(StrictDecisionLogModel):
    action_count: int = Field(ge=0)
    accepted_count: int = Field(ge=0)
    corrected_count: int = Field(ge=0)
    rejected_count: int = Field(ge=0)
    source_ref_count: int = Field(ge=0)
    runtime_mutation_count: Literal[0] = 0
    package_mutation_count: Literal[0] = 0
    raw_payloads_embedded: Literal[False] = False


class ReviewDecisionBoundary(StrictDecisionLogModel):
    append_only: Literal[True] = True
    source_mutation_allowed: Literal[False] = False
    package_mutation_allowed: Literal[False] = False
    runtime_mutation_allowed: Literal[False] = False
    phase1_runtime_mutation_allowed: Literal[False] = False
    phase2_writeback_allowed: Literal[False] = False
    external_api_calls_made: Literal[False] = False
    admin_api_integration: Literal[False] = False
    compiles_mission_graph: Literal[False] = False
    raw_payloads_embedded: Literal[False] = False
    notes: list[str] = Field(default_factory=list)


class ReviewApplySummary(StrictDecisionLogModel):
    accepted_candidate_refs: list[str] = Field(default_factory=list)
    corrected_candidate_refs: list[str] = Field(default_factory=list)
    rejected_candidate_refs: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    runtime_mutation_count: Literal[0] = 0
    package_mutation_count: Literal[0] = 0
    phase1_runtime_mutation_allowed: Literal[False] = False
    phase2_writeback_allowed: Literal[False] = False
    compiles_mission_graph: Literal[False] = False
    notes: list[str] = Field(default_factory=list)


class PreTripReviewDecisionLog(StrictDecisionLogModel):
    log_id: str
    artifact_kind: Literal["pretrip_review_decision_log"] = "pretrip_review_decision_log"
    project_id: str
    source_draft_log_ref: str
    source_review_queue_manifest_ref: str
    decisions: list[ReviewDecisionRecord]
    counts: ReviewDecisionCounts
    apply_summary: ReviewApplySummary
    boundary: ReviewDecisionBoundary = Field(default_factory=ReviewDecisionBoundary)
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_log_boundary(self) -> "PreTripReviewDecisionLog":
        if any(not decision.source_review_queue_item_refs for decision in self.decisions):
            raise ValueError("review decisions require source review queue refs")
        if any(decision.source_mutation_allowed for decision in self.decisions):
            raise ValueError("decision log fixture must not mutate source artifacts")
        if any(decision.package_mutation_allowed for decision in self.decisions):
            raise ValueError("decision log fixture must not mutate packages")
        if any(decision.runtime_mutation_allowed for decision in self.decisions):
            raise ValueError("decision log fixture must not mutate runtime state")
        _assert_no_raw_payload_fragments(self.model_dump(mode="json"))
        return self

    def to_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n"


def build_chilai_review_decision_log(project_root: Path | str) -> PreTripReviewDecisionLog:
    project_path = _resolve_chilai_project_path(Path(project_root))
    fixture_root = project_path.parent
    project = _load_json(project_path)
    project_id = str(project["project_id"])
    draft_log_ref = str(project["review_draft_log_ref"])
    review_queue_ref = str(project["review_queue_manifest_ref"])
    draft_log = _load_json(fixture_root / draft_log_ref)
    review_queue = _load_json(fixture_root / review_queue_ref)
    queue_refs_by_candidate = _index_queue_refs(review_queue)

    decisions = [
        _decision_from_draft_action(
            draft_log["actions"][0],
            project_id=project_id,
            decision=ReviewDecision.ACCEPTED,
            reviewer_alias="trip_leader",
            decided_at="2026-05-15T10:00:00+08:00",
            queue_refs_by_candidate=queue_refs_by_candidate,
            summary="Accepted contour review note as candidate-only planning context.",
        ),
        _decision_from_draft_action(
            draft_log["actions"][1],
            project_id=project_id,
            decision=ReviewDecision.CORRECTED,
            reviewer_alias="trip_leader",
            decided_at="2026-05-15T10:05:00+08:00",
            queue_refs_by_candidate=queue_refs_by_candidate,
            summary="Corrected segment policy review fields while keeping them candidate-only.",
            correction=ReviewDecisionCorrection(
                summary="Keep the conservative daylight and retreat flags, but require water status to remain reviewer-confirmed.",
                field_updates={
                    "review_state_after_edit": "accepted_with_human_correction",
                    "water_available": "reviewer_confirmed_unknown",
                },
                replacement_ref_ids=["review_queue.chilai_nanhua_day1.segment_policy.policy_candidate.chilai_nanhua_day1.seg.001"],
            ),
        ),
        _decision_from_draft_action(
            draft_log["actions"][2],
            project_id=project_id,
            decision=ReviewDecision.REJECTED,
            reviewer_alias="trip_leader",
            decided_at="2026-05-15T10:10:00+08:00",
            queue_refs_by_candidate=queue_refs_by_candidate,
            summary="Rejected POI corridor policy edit as insufficient for accepted planning assumptions.",
        ),
    ]
    counts_by_decision = Counter(decision.decision.value for decision in decisions)
    source_refs = sorted(
        {
            source_ref.source_ref
            for decision in decisions
            for source_ref in decision.source_review_queue_item_refs
        }
    )

    return PreTripReviewDecisionLog(
        log_id=f"review_decision_log.{project_id}.v0",
        project_id=project_id,
        source_draft_log_ref=draft_log_ref,
        source_review_queue_manifest_ref=review_queue_ref,
        decisions=decisions,
        counts=ReviewDecisionCounts(
            action_count=len(decisions),
            accepted_count=counts_by_decision["accepted"],
            corrected_count=counts_by_decision["corrected"],
            rejected_count=counts_by_decision["rejected"],
            source_ref_count=len(source_refs),
        ),
        apply_summary=ReviewApplySummary(
            accepted_candidate_refs=[
                decision.candidate_ref for decision in decisions if decision.decision == ReviewDecision.ACCEPTED
            ],
            corrected_candidate_refs=[
                decision.candidate_ref for decision in decisions if decision.decision == ReviewDecision.CORRECTED
            ],
            rejected_candidate_refs=[
                decision.candidate_ref for decision in decisions if decision.decision == ReviewDecision.REJECTED
            ],
            source_refs=source_refs,
            notes=[
                "Apply summary is a fixture-only administrative summary, not a package patch.",
                "No Phase 1 runtime state, Phase 2 Brain state, source artifact, or MissionGraph output is mutated.",
            ],
        ),
        boundary=ReviewDecisionBoundary(
            notes=[
                "Decision log accepts, corrects, or rejects selected draft review actions only.",
                "Records are append-only pointers to review queue items and candidate refs.",
                "No raw source payloads, external API calls, admin API writes, package mutation, runtime mutation, Phase 2 writeback, or MissionGraph compile is performed.",
            ],
        ),
        notes=[
            "Representative Phase 4 slice A fixture for accepted admin review decisions.",
            "Uses the current three Chilai review draft actions as the complete input set.",
        ],
    )


def load_review_decision_log(path: Path | str) -> PreTripReviewDecisionLog:
    return PreTripReviewDecisionLog.model_validate_json(
        Path(path).read_text(encoding="utf-8")
    )


def _decision_from_draft_action(
    draft_action: dict[str, Any],
    *,
    project_id: str,
    decision: ReviewDecision,
    reviewer_alias: str,
    decided_at: str,
    queue_refs_by_candidate: dict[str, SourceReviewQueueItemRef],
    summary: str,
    correction: ReviewDecisionCorrection | None = None,
) -> ReviewDecisionRecord:
    candidate_ref = str(draft_action["candidate_ref"])
    source_queue_ref = queue_refs_by_candidate.get(candidate_ref) or SourceReviewQueueItemRef(
        review_queue_manifest_id=f"review_draft_log.{project_id}.v0",
        item_id=str(draft_action["action_id"]),
        source_ref=str(draft_action["source_ref"]),
        candidate_ref=candidate_ref,
    )
    return ReviewDecisionRecord(
        decision_id=f"review_decision.{project_id}.{decision.value}.{candidate_ref}",
        draft_action_id=str(draft_action["action_id"]),
        decision=decision,
        candidate_ref=candidate_ref,
        target_ids=_target_ids(draft_action),
        source_review_queue_item_refs=[source_queue_ref],
        reviewer_alias=reviewer_alias,
        decided_at=decided_at,
        summary=summary,
        correction=correction,
    )


def _target_ids(draft_action: dict[str, Any]) -> list[str]:
    proposed_fields = draft_action.get("proposed_fields", {})
    for key in ("target_segment_refs",):
        value = proposed_fields.get(key)
        if isinstance(value, list) and value:
            return [str(item) for item in value]
    for key in ("segment_candidate_id", "category", "candidate_ref"):
        value = proposed_fields.get(key)
        if value:
            return [str(value)]
    return [str(draft_action["candidate_ref"])]


def _index_queue_refs(review_queue: dict[str, Any]) -> dict[str, SourceReviewQueueItemRef]:
    manifest_id = str(review_queue["manifest_id"])
    refs: dict[str, SourceReviewQueueItemRef] = {}
    for item in review_queue.get("items", []):
        candidate_ref = str(item["candidate_ref"])
        refs[candidate_ref] = SourceReviewQueueItemRef(
            review_queue_manifest_id=manifest_id,
            item_id=str(item["item_id"]),
            source_ref=str(item["source_ref"]),
            candidate_ref=candidate_ref,
        )
    return refs


def _resolve_chilai_project_path(path: Path) -> Path:
    if path.is_file():
        return path
    if (path / "project.json").exists():
        return path / "project.json"
    candidate = path / DEFAULT_CHILAI_PROJECT_REF
    if candidate.exists():
        return candidate
    raise FileNotFoundError(f"could not find Chilai pretrip project.json under {path}")


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _assert_no_raw_payload_fragments(payload: object) -> None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key != "raw_payloads_embedded":
                _reject_raw_payload_fragment(str(key))
            _assert_no_raw_payload_fragments(value)
        return
    if isinstance(payload, list):
        for item in payload:
            _assert_no_raw_payload_fragments(item)
        return
    if isinstance(payload, str):
        _reject_raw_payload_fragment(payload)


def _reject_raw_payload_fragment(value: str) -> None:
    forbidden_fragments = [
        "/safety",
        "Phase1IncidentBridge",
        "SCOUT_PHASE2_INCIDENT_BRIDGE",
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
        "incident_samples",
        "raw_samples",
        "sample_payload",
        "elevation_grid",
        "terrain_tile",
        "raw_payload",
        "raw_payload_fragment",
        "payload_fragment",
        "source_payload",
        "admin_api.py",
        "requests.",
        "httpx.",
    ]
    lowered = value.lower()
    for fragment in forbidden_fragments:
        if fragment.lower() in lowered:
            raise ValueError(f"review decision fixture contains forbidden raw/runtime fragment: {fragment}")
