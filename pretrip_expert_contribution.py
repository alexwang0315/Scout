from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ContributionOperation(StrEnum):
    ADD_CANDIDATE = "add_candidate"
    REMOVE_CANDIDATE = "remove_candidate"
    UPDATE_CANDIDATE = "update_candidate"
    ADD_IMPORT_REQUEST = "add_import_request"
    UPDATE_IMPORT_REQUEST = "update_import_request"
    REMOVE_IMPORT_REQUEST = "remove_import_request"


class ContributionTargetKind(StrEnum):
    CHECKPOINT_CANDIDATE = "checkpoint_candidate"
    SEGMENT_CANDIDATE = "segment_candidate"
    RETREAT_ROUTE_CANDIDATE = "retreat_route_candidate"
    POI_CANDIDATE = "poi_candidate"
    HAZARD_CANDIDATE = "hazard_candidate"
    EXTERNAL_IMPORT_REQUEST = "external_import_request"


class ExpertContributionModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExpertContributionAiAssist(ExpertContributionModel):
    interpretation_id: str
    interpretation_kind: Literal["ModelInterpretation"] = "ModelInterpretation"
    memory_seed_candidate: Literal[True] = True
    memory_writeback_allowed: Literal[False] = False
    proposed_memory_tags: tuple[str, ...] = Field(default_factory=tuple)
    summary: str


class ExpertContributionRecord(ExpertContributionModel):
    contribution_id: str
    contributor_alias: str
    contributor_role: Literal["admin_expert", "trip_leader", "community_reviewer"]
    created_at: str
    source_surface: Literal["admin_candidate_set", "admin_external_import_queue"]
    operation: ContributionOperation
    target_kind: ContributionTargetKind
    target_ref: str
    target_artifact_ref: str
    summary: str
    rationale: str
    evidence_status: Literal["admin_claim", "community_report_reference", "field_observation_pending"]
    review_state: Literal["proposed", "needs_human_review", "accepted", "rejected"] = "needs_human_review"
    applies_to_candidate_set: bool
    applied_to_fixture_candidate_set: Literal[False] = False
    applies_to_external_import_queue: bool
    applied_to_fixture_external_import_queue: Literal[False] = False
    ai_assist: ExpertContributionAiAssist

    @model_validator(mode="after")
    def enforce_target_alignment(self) -> "ExpertContributionRecord":
        if self.target_kind == ContributionTargetKind.EXTERNAL_IMPORT_REQUEST:
            if not self.operation.value.endswith("import_request"):
                raise ValueError("external import targets require import-request operations")
            if not self.applies_to_external_import_queue:
                raise ValueError("external import targets must apply to the import queue")
            if self.applies_to_candidate_set:
                raise ValueError("external import targets must not apply to the candidate set")
        else:
            if self.operation.value.endswith("import_request"):
                raise ValueError("candidate targets require candidate operations")
            if not self.applies_to_candidate_set:
                raise ValueError("candidate targets must apply to the candidate set")
            if self.applies_to_external_import_queue:
                raise ValueError("candidate targets must not apply to the import queue")
        _assert_no_raw_payload_fragments(self.model_dump(mode="json"))
        return self


class ExpertContributionCounts(ExpertContributionModel):
    contribution_count: int = Field(ge=0)
    candidate_set_edit_count: int = Field(ge=0)
    external_import_edit_count: int = Field(ge=0)
    memory_seed_candidate_count: int = Field(ge=0)
    brain_writeback_count: Literal[0] = 0
    raw_payload_count: Literal[0] = 0


class ExpertContributionBoundary(ExpertContributionModel):
    candidate_set_edit_intent_only: Literal[True] = True
    external_import_edit_intent_only: Literal[True] = True
    requires_human_review_before_apply: Literal[True] = True
    memory_seed_candidate_only: Literal[True] = True
    brain_writeback_allowed: Literal[False] = False
    package_mutation_allowed: Literal[False] = False
    mission_graph_mutation_allowed: Literal[False] = False
    runtime_mutation_allowed: Literal[False] = False
    phase1_runtime_mutation_allowed: Literal[False] = False
    phase2_writeback_allowed: Literal[False] = False
    external_api_calls_made: Literal[False] = False
    raw_payloads_embedded: Literal[False] = False
    notes: tuple[str, ...] = Field(default_factory=tuple)


class ExpertContributionLog(ExpertContributionModel):
    log_id: str
    artifact_kind: Literal["pretrip_expert_contribution_log"] = (
        "pretrip_expert_contribution_log"
    )
    project_id: str
    status: Literal["candidate_memory_seed_only"] = "candidate_memory_seed_only"
    records: tuple[ExpertContributionRecord, ...]
    counts: ExpertContributionCounts
    boundary: ExpertContributionBoundary
    notes: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def enforce_log_counts_and_boundaries(self) -> "ExpertContributionLog":
        if self.counts.contribution_count != len(self.records):
            raise ValueError("contribution_count must match records")
        candidate_edits = sum(1 for record in self.records if record.applies_to_candidate_set)
        import_edits = sum(1 for record in self.records if record.applies_to_external_import_queue)
        memory_seeds = sum(1 for record in self.records if record.ai_assist.memory_seed_candidate)
        if self.counts.candidate_set_edit_count != candidate_edits:
            raise ValueError("candidate_set_edit_count must match records")
        if self.counts.external_import_edit_count != import_edits:
            raise ValueError("external_import_edit_count must match records")
        if self.counts.memory_seed_candidate_count != memory_seeds:
            raise ValueError("memory_seed_candidate_count must match records")
        _assert_no_raw_payload_fragments(self.model_dump(mode="json"))
        return self

    def to_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n"


def build_chilai_expert_contribution_log() -> ExpertContributionLog:
    records = (
        ExpertContributionRecord(
            contribution_id="expert_contribution.chilai_nanhua_day1.add_checkpoint.trail_condition_reference.v0",
            contributor_alias="trip_leader",
            contributor_role="admin_expert",
            created_at="2026-05-15T22:30:00+08:00",
            source_surface="admin_candidate_set",
            operation=ContributionOperation.ADD_CANDIDATE,
            target_kind=ContributionTargetKind.CHECKPOINT_CANDIDATE,
            target_ref="admin_added_checkpoint.chilai_nanhua_day1.trail_condition_reference.v0",
            target_artifact_ref="candidates/checkpoints.json",
            summary="Admin may add route-specific checkpoints when recent hiker reports identify decision points missing from AI-generated candidates.",
            rationale="Fresh trail condition reports can be richer than static map sources, but must remain review-gated until the admin accepts exact placement.",
            evidence_status="field_observation_pending",
            applies_to_candidate_set=True,
            applies_to_external_import_queue=False,
            ai_assist=ExpertContributionAiAssist(
                interpretation_id="model_interpretation.expert_contribution.add_checkpoint.trail_condition_reference.v0",
                proposed_memory_tags=(
                    "taiwan_mountain_route_planning",
                    "expert_added_checkpoint",
                    "recent_hiker_report",
                ),
                summary="If accepted, remember this admin as a contributor whose recent trail-condition checkpoints can improve future candidate generation.",
            ),
        ),
        ExpertContributionRecord(
            contribution_id="expert_contribution.chilai_nanhua_day1.update_retreat.return_to_entry.v0",
            contributor_alias="trip_leader",
            contributor_role="admin_expert",
            created_at="2026-05-15T22:35:00+08:00",
            source_surface="admin_candidate_set",
            operation=ContributionOperation.UPDATE_CANDIDATE,
            target_kind=ContributionTargetKind.RETREAT_ROUTE_CANDIDATE,
            target_ref="retreat.chilai_nanhua_day1.return_to_entry",
            target_artifact_ref="candidates/retreat_routes.json",
            summary="Admin clarified that this route should default to return-to-entry retreat rather than assuming multiple descent exits.",
            rationale="The trail is mostly out-and-back for practical retreat planning after entering the mountain area.",
            evidence_status="admin_claim",
            applies_to_candidate_set=True,
            applies_to_external_import_queue=False,
            ai_assist=ExpertContributionAiAssist(
                interpretation_id="model_interpretation.expert_contribution.retreat.return_to_entry.v0",
                proposed_memory_tags=(
                    "route_retreat_semantics",
                    "return_to_entry_default",
                    "admin_route_expertise",
                ),
                summary="If accepted, prefer return-to-entry retreat assumptions for similar routes unless reviewed evidence indicates practical exit alternatives.",
            ),
        ),
        ExpertContributionRecord(
            contribution_id="expert_contribution.chilai_nanhua_day1.add_import.recent_hiker_report.v0",
            contributor_alias="trip_leader",
            contributor_role="admin_expert",
            created_at="2026-05-15T22:40:00+08:00",
            source_surface="admin_external_import_queue",
            operation=ContributionOperation.ADD_IMPORT_REQUEST,
            target_kind=ContributionTargetKind.EXTERNAL_IMPORT_REQUEST,
            target_ref="external_import.chilai_nanhua_day1.recent_hiker_report.placeholder",
            target_artifact_ref="outputs/external_import_queue.json",
            summary="Admin may add URL-only import requests for recent hiker condition reports as planning references.",
            rationale="Recent human reports can explain route features that base maps, DTM, and guide timing do not capture.",
            evidence_status="community_report_reference",
            applies_to_candidate_set=False,
            applies_to_external_import_queue=True,
            ai_assist=ExpertContributionAiAssist(
                interpretation_id="model_interpretation.expert_contribution.import.recent_hiker_report.v0",
                proposed_memory_tags=(
                    "community_route_condition_reference",
                    "external_import_request",
                    "human_review_required",
                ),
                summary="If accepted, remember that this admin values recent route-condition reports as candidate-generation evidence, not as automatic field truth.",
            ),
        ),
    )
    return ExpertContributionLog(
        log_id="expert_contribution_log.chilai_nanhua_day1.v0",
        project_id="chilai_nanhua_day1",
        records=records,
        counts=ExpertContributionCounts(
            contribution_count=len(records),
            candidate_set_edit_count=sum(record.applies_to_candidate_set for record in records),
            external_import_edit_count=sum(
                record.applies_to_external_import_queue for record in records
            ),
            memory_seed_candidate_count=len(records),
        ),
        boundary=ExpertContributionBoundary(
            notes=(
                "Expert contributions record admin edits to AI-generated candidates and import requests.",
                "This artifact is an intent log and memory-seed candidate, not a final candidate-set mutation.",
                "Accepted contributions may later train future candidate generation or seed Phase 2 memory through an explicit reviewed import path.",
            ),
        ),
        notes=(
            "Phase 4 expert-contribution fixture for admin candidate-set and external-import edits.",
            "No raw reports, crawled pages, final MissionGraph changes, or Brain writeback are embedded.",
        ),
    )


def load_expert_contribution_log(path: Path | str) -> ExpertContributionLog:
    return ExpertContributionLog.model_validate_json(Path(path).read_text(encoding="utf-8"))


def expert_contribution_log_to_json(log: ExpertContributionLog) -> str:
    return log.to_json()


def _assert_no_raw_payload_fragments(payload: object) -> None:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    for fragment in (
        "raw_html",
        "snapshot_body",
        "raw_gpx",
        "raw_photo",
        "raw_dtm",
        "ObservedFact",
        "write_observed_fact",
        "/safety/",
    ):
        if fragment in serialized:
            raise ValueError(f"expert contribution contains forbidden raw/runtime fragment: {fragment}")
