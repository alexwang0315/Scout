from __future__ import annotations

import json
import hashlib
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pretrip_route_note_ln_proposals import (
    RouteNoteLnProposalSet,
    load_route_note_ln_proposals,
)


AdminDisposition = Literal[
    "promote_hint",
    "promote_warning",
    "ignore",
    "field_verify",
]

ALLOWED_ADMIN_DISPOSITIONS: tuple[AdminDisposition, ...] = (
    "promote_hint",
    "promote_warning",
    "ignore",
    "field_verify",
)


class RouteNoteReviewOptionsModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RouteNoteReviewOptionsBoundary(RouteNoteReviewOptionsModel):
    source_ln_proposals_only: Literal[True] = True
    candidate_only: Literal[True] = True
    draft_only: Literal[True] = True
    review_options_only: Literal[True] = True
    decision_recording_allowed: Literal[False] = False
    package_mutation_allowed: Literal[False] = False
    mission_graph_mutation_allowed: Literal[False] = False
    runtime_mutation_allowed: Literal[False] = False
    phase1_runtime_mutation_allowed: Literal[False] = False
    phase2_writeback_allowed: Literal[False] = False
    raw_gpx_embedded: Literal[False] = False
    crawler_or_network_source_allowed: Literal[False] = False
    notes: tuple[str, ...] = Field(default_factory=tuple)


class RouteNoteReviewOptionsCounts(RouteNoteReviewOptionsModel):
    source_proposal_count: int = Field(ge=0)
    review_option_count: int = Field(ge=0)
    candidate_only_count: int = Field(ge=0)
    draft_only_count: int = Field(ge=0)
    decision_recorded_count: Literal[0] = 0
    package_mutation_count: Literal[0] = 0
    mission_graph_mutation_count: Literal[0] = 0
    runtime_mutation_count: Literal[0] = 0
    phase1_runtime_mutation_count: Literal[0] = 0
    phase2_writeback_count: Literal[0] = 0
    raw_gpx_payload_count: Literal[0] = 0


class RouteNoteReviewOption(RouteNoteReviewOptionsModel):
    option_id: str
    source_proposal_id: str
    source_route_note_candidate_id: str
    source_waypoint_index: int = Field(ge=0)
    source_note_category: Literal["hazard_hint", "route_condition_hint"]
    proposal_kind: Literal["warning_coverage", "hint_coverage"]
    proposed_coverage_label: str
    route_note_summary: str
    source_refs: tuple[str, ...] = Field(default_factory=tuple)
    source_attribution: tuple[dict[str, Any], ...] = Field(default_factory=tuple)
    extractor_version: str = "pretrip_route_note_review_options.v0"
    extractor_method: str = "pretrip_route_note_review_options.build_route_note_review_options"
    pydantic_ai_prompt_version: str = "deterministic_schema_ready.no_live_model.v0"
    model_output_sha256: str = "manual_fixture_no_model_hash"
    model_output_summary: str = "manual fixture route-note review options"
    confidence: Literal["low", "medium", "high", "unknown"] = "medium"
    stale_risk: Literal["unknown", "low", "medium", "high"] = "unknown"
    review_state: Literal["draft"] = "draft"
    allowed_admin_dispositions: tuple[AdminDisposition, ...] = ALLOWED_ADMIN_DISPOSITIONS
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False
    draft_only: Literal[True] = True
    decision_recorded: Literal[False] = False
    selected_admin_disposition: None = None
    package_mutation_candidate: Literal[False] = False
    mission_graph_mutation_candidate: Literal[False] = False
    runtime_mutation_candidate: Literal[False] = False
    phase1_runtime_mutation_candidate: Literal[False] = False
    phase2_writeback_candidate: Literal[False] = False
    raw_gpx_embedded: Literal[False] = False

    @model_validator(mode="after")
    def _enforce_review_option_boundary(self) -> "RouteNoteReviewOption":
        if self.allowed_admin_dispositions != ALLOWED_ADMIN_DISPOSITIONS:
            raise ValueError("allowed_admin_dispositions must match the admin review set")
        return self


class RouteNoteReviewOptions(RouteNoteReviewOptionsModel):
    artifact_id: str
    artifact_kind: Literal["pretrip_route_note_review_options"] = (
        "pretrip_route_note_review_options"
    )
    project_id: str
    source_artifact_id: str
    status: Literal["candidate_only_draft_only"] = "candidate_only_draft_only"
    counts: RouteNoteReviewOptionsCounts
    boundary: RouteNoteReviewOptionsBoundary
    options: tuple[RouteNoteReviewOption, ...]
    notes: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _enforce_counts_and_boundary(self) -> "RouteNoteReviewOptions":
        if self.counts.source_proposal_count != len(self.options):
            raise ValueError("source_proposal_count must match options")
        if self.counts.review_option_count != len(self.options):
            raise ValueError("review_option_count must match options")
        if self.counts.candidate_only_count != len(self.options):
            raise ValueError("candidate_only_count must match options")
        if self.counts.draft_only_count != len(self.options):
            raise ValueError("draft_only_count must match options")
        if any(option.decision_recorded for option in self.options):
            raise ValueError("route-note review options cannot record decisions")
        return self

    def to_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n"


def build_route_note_review_options(
    proposal_set: RouteNoteLnProposalSet | dict,
) -> RouteNoteReviewOptions:
    source = (
        proposal_set
        if isinstance(proposal_set, RouteNoteLnProposalSet)
        else RouteNoteLnProposalSet.model_validate(proposal_set)
    )
    options = tuple(_review_option_from_proposal(proposal) for proposal in source.proposals)
    return RouteNoteReviewOptions(
        artifact_id=f"route_note_review_options.{source.project_id}.v0",
        project_id=source.project_id,
        source_artifact_id=source.artifact_id,
        counts=RouteNoteReviewOptionsCounts(
            source_proposal_count=len(source.proposals),
            review_option_count=len(options),
            candidate_only_count=len(options),
            draft_only_count=len(options),
        ),
        boundary=RouteNoteReviewOptionsBoundary(
            notes=(
                "Review options are a candidate-only admin draft projection from route-note Ln proposals.",
                "Allowed dispositions are labels for later admin review UI wiring and do not record a decision.",
                "This artifact does not mutate packages, mission graphs, runtime state, Phase 1, or Phase 2.",
            ),
        ),
        options=options,
        notes=(
            "One review-options record is emitted for each route-note Ln proposal.",
            "Main integration can later wire these options to review UI and decision storage.",
        ),
    )


def load_route_note_review_options_from_ln_proposals(
    path: Path | str,
) -> RouteNoteReviewOptions:
    return build_route_note_review_options(load_route_note_ln_proposals(path))


def load_route_note_review_options(path: Path | str) -> RouteNoteReviewOptions:
    return RouteNoteReviewOptions.model_validate_json(Path(path).read_text(encoding="utf-8"))


def route_note_review_options_to_json(review_options: RouteNoteReviewOptions) -> str:
    return review_options.to_json()


def _review_option_from_proposal(proposal) -> RouteNoteReviewOption:
    return RouteNoteReviewOption(
        option_id=f"route_note_review_option.{proposal.proposal_id}",
        source_proposal_id=proposal.proposal_id,
        source_route_note_candidate_id=proposal.source_route_note_candidate_id,
        source_waypoint_index=proposal.source_waypoint_index,
        source_note_category=proposal.source_note_category,
        proposal_kind=proposal.proposal_kind,
        proposed_coverage_label=proposal.proposed_coverage_label,
        route_note_summary=proposal.route_note_summary,
        source_refs=(proposal.proposal_id, *tuple(proposal.source_refs)),
        source_attribution=(
            {
                "source_kind": "route_note_ln_proposal",
                "source_ref": proposal.proposal_id,
                "source_artifact_refs": tuple(proposal.source_refs),
                "source_waypoint_index": proposal.source_waypoint_index,
                "extractor_version": "pretrip_route_note_review_options.v0",
                "extractor_method": "pretrip_route_note_review_options.build_route_note_review_options",
                "candidate_only": True,
                "draft_only": True,
                "runtime_safety_truth": False,
            },
        ),
        model_output_sha256=_sha256_text(
            json.dumps(
                {
                    "source_proposal_id": proposal.proposal_id,
                    "allowed_admin_dispositions": ALLOWED_ADMIN_DISPOSITIONS,
                    "proposal_kind": proposal.proposal_kind,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        ),
        model_output_summary=(
            f"draft review dispositions for {proposal.proposal_kind}: "
            f"{', '.join(ALLOWED_ADMIN_DISPOSITIONS)}"
        ),
        confidence=proposal.confidence,
        stale_risk=proposal.stale_risk,
    )


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
