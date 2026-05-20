from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pretrip_route_note_candidates import RouteNoteCandidateSet, load_route_note_candidates


class RouteNoteLnProposalModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RouteNoteLnProposalBoundary(RouteNoteLnProposalModel):
    source_route_notes_only: Literal[True] = True
    candidate_only: Literal[True] = True
    human_review_required_before_use: Literal[True] = True
    observed_fact_allowed: Literal[False] = False
    derived_measurement_allowed: Literal[False] = False
    package_mutation_allowed: Literal[False] = False
    mission_graph_mutation_allowed: Literal[False] = False
    runtime_mutation_allowed: Literal[False] = False
    phase1_runtime_mutation_allowed: Literal[False] = False
    phase2_writeback_allowed: Literal[False] = False
    raw_gpx_embedded: Literal[False] = False
    crawler_or_network_source_allowed: Literal[False] = False
    notes: tuple[str, ...] = Field(default_factory=tuple)


class RouteNoteLnProposalCounts(RouteNoteLnProposalModel):
    source_route_note_count: int = Field(ge=0)
    source_potential_ln_signal_count: int = Field(ge=0)
    proposal_count: int = Field(ge=0)
    hint_coverage_proposal_count: int = Field(ge=0)
    warning_coverage_proposal_count: int = Field(ge=0)
    human_review_required_count: int = Field(ge=0)
    observed_fact_count: Literal[0] = 0
    derived_measurement_count: Literal[0] = 0
    runtime_mutation_count: Literal[0] = 0
    phase1_runtime_mutation_count: Literal[0] = 0
    phase2_writeback_count: Literal[0] = 0
    raw_gpx_payload_count: Literal[0] = 0


class RouteNoteLnProposal(RouteNoteLnProposalModel):
    proposal_id: str
    source_route_note_candidate_id: str
    source_waypoint_index: int = Field(ge=0)
    lat: float
    lon: float
    source_note_category: Literal["hazard_hint", "route_condition_hint"]
    proposal_kind: Literal["warning_coverage", "hint_coverage"]
    proposed_ln_record_kind: Literal["ln_proposal_candidate"] = "ln_proposal_candidate"
    proposed_coverage_label: str
    route_note_summary: str
    human_review_required: Literal[True] = True
    candidate_only: Literal[True] = True
    scout_interpretation: Literal["ModelInterpretation"] = "ModelInterpretation"
    observed_fact_candidate: Literal[False] = False
    derived_measurement_candidate: Literal[False] = False
    runtime_mutation_candidate: Literal[False] = False
    phase1_runtime_mutation_candidate: Literal[False] = False
    phase2_writeback_candidate: Literal[False] = False
    raw_gpx_embedded: Literal[False] = False

    @model_validator(mode="after")
    def _proposal_matches_source_category(self) -> "RouteNoteLnProposal":
        expected = (
            "warning_coverage"
            if self.source_note_category == "hazard_hint"
            else "hint_coverage"
        )
        if self.proposal_kind != expected:
            raise ValueError("proposal_kind must match source_note_category")
        return self


class RouteNoteLnProposalSet(RouteNoteLnProposalModel):
    artifact_id: str
    artifact_kind: Literal["pretrip_route_note_ln_proposals"] = (
        "pretrip_route_note_ln_proposals"
    )
    project_id: str
    source_artifact_id: str
    status: Literal["candidate_only"] = "candidate_only"
    counts: RouteNoteLnProposalCounts
    boundary: RouteNoteLnProposalBoundary
    proposals: tuple[RouteNoteLnProposal, ...]
    notes: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _enforce_candidate_boundaries(self) -> "RouteNoteLnProposalSet":
        kinds = Counter(proposal.proposal_kind for proposal in self.proposals)
        if self.counts.proposal_count != len(self.proposals):
            raise ValueError("proposal_count must match proposals")
        if self.counts.source_potential_ln_signal_count != len(self.proposals):
            raise ValueError("source_potential_ln_signal_count must match proposals")
        if self.counts.hint_coverage_proposal_count != kinds["hint_coverage"]:
            raise ValueError("hint_coverage_proposal_count must match proposals")
        if self.counts.warning_coverage_proposal_count != kinds["warning_coverage"]:
            raise ValueError("warning_coverage_proposal_count must match proposals")
        if self.counts.human_review_required_count != len(self.proposals):
            raise ValueError("human_review_required_count must match proposals")
        if any(not proposal.human_review_required for proposal in self.proposals):
            raise ValueError("all route-note Ln proposals require HumanReview")
        return self

    def to_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n"


def build_route_note_ln_proposals(
    route_note_candidates: RouteNoteCandidateSet,
) -> RouteNoteLnProposalSet:
    proposals = tuple(
        _proposal_from_route_note(candidate)
        for candidate in route_note_candidates.candidates
        if candidate.potential_ln_signal
    )
    kinds = Counter(proposal.proposal_kind for proposal in proposals)
    return RouteNoteLnProposalSet(
        artifact_id=f"route_note_ln_proposals.{route_note_candidates.project_id}.v0",
        project_id=route_note_candidates.project_id,
        source_artifact_id=route_note_candidates.artifact_id,
        counts=RouteNoteLnProposalCounts(
            source_route_note_count=len(route_note_candidates.candidates),
            source_potential_ln_signal_count=route_note_candidates.counts.potential_ln_signal_count,
            proposal_count=len(proposals),
            hint_coverage_proposal_count=kinds["hint_coverage"],
            warning_coverage_proposal_count=kinds["warning_coverage"],
            human_review_required_count=len(proposals),
        ),
        boundary=RouteNoteLnProposalBoundary(
            notes=(
                "Route-note Ln proposals are a downstream planning candidate projection only.",
                "Human review is required before any hint or warning coverage can become an accepted planning assumption.",
                "This artifact does not mutate Phase 1, Phase 2, runtime state, MissionGraph, or PreTripPackage records.",
            ),
        ),
        proposals=proposals,
        notes=(
            "Only route notes already marked potential_ln_signal are proposed for Ln coverage.",
            "Hazard notes become warning coverage proposals; route-condition notes become hint coverage proposals.",
        ),
    )


def load_route_note_ln_proposals_from_route_note_fixture(
    path: Path | str,
) -> RouteNoteLnProposalSet:
    return build_route_note_ln_proposals(load_route_note_candidates(path))


def load_route_note_ln_proposals(path: Path | str) -> RouteNoteLnProposalSet:
    return RouteNoteLnProposalSet.model_validate_json(Path(path).read_text(encoding="utf-8"))


def route_note_ln_proposals_to_json(proposal_set: RouteNoteLnProposalSet) -> str:
    return proposal_set.to_json()


def _proposal_from_route_note(candidate) -> RouteNoteLnProposal:
    proposal_kind: Literal["warning_coverage", "hint_coverage"]
    proposed_coverage_label: str
    if candidate.note_category == "hazard_hint":
        proposal_kind = "warning_coverage"
        proposed_coverage_label = "route_note_warning_coverage"
    elif candidate.note_category == "route_condition_hint":
        proposal_kind = "hint_coverage"
        proposed_coverage_label = "route_note_hint_coverage"
    else:
        raise ValueError("route note must be a potential hazard or route-condition Ln signal")

    return RouteNoteLnProposal(
        proposal_id=f"ln_proposal.{candidate.candidate_id}",
        source_route_note_candidate_id=candidate.candidate_id,
        source_waypoint_index=candidate.source_waypoint_index,
        lat=candidate.lat,
        lon=candidate.lon,
        source_note_category=candidate.note_category,
        proposal_kind=proposal_kind,
        proposed_coverage_label=proposed_coverage_label,
        route_note_summary=candidate.normalized_note,
    )
