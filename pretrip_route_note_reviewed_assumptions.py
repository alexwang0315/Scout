from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pretrip_route_note_disposition_store import (
    DEFAULT_ROUTE_NOTE_DISPOSITION_LOG_REF,
    RouteNoteDispositionLog,
    RouteNoteDispositionRecord,
    load_route_note_disposition_log,
)


DEFAULT_ROUTE_NOTE_REVIEWED_ASSUMPTIONS_REF = (
    "outputs/route_note_reviewed_assumptions.json"
)
REPO_FIXTURE_PROJECTS_ROOT = (
    Path(__file__).resolve().parent / "tests" / "fixtures" / "pretrip" / "projects"
)


class RouteNoteReviewedAssumptionModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RouteNoteReviewedAssumptionBoundary(RouteNoteReviewedAssumptionModel):
    local_workspace_only: Literal[True] = True
    source_route_note_dispositions_only: Literal[True] = True
    reviewed_planning_assumption_candidate: Literal[True] = True
    ln_expansion_candidate_only: Literal[True] = True
    observed_fact_created: Literal[False] = False
    derived_measurement_created: Literal[False] = False
    package_mutation_allowed: Literal[False] = False
    mission_graph_mutation_allowed: Literal[False] = False
    runtime_activation_allowed: Literal[False] = False
    phase1_runtime_mutation_allowed: Literal[False] = False
    phase2_writeback_allowed: Literal[False] = False
    raw_gpx_embedded: Literal[False] = False
    crawler_or_network_source_allowed: Literal[False] = False
    notes: list[str] = Field(default_factory=list)


class RouteNoteReviewedAssumptionCounts(RouteNoteReviewedAssumptionModel):
    disposition_count: int = Field(ge=0)
    accepted_interpretation_count: int = Field(ge=0)
    ln_expansion_candidate_count: int = Field(ge=0)
    field_verification_request_count: int = Field(ge=0)
    ignored_count: int = Field(ge=0)
    warning_expansion_candidate_count: int = Field(ge=0)
    hint_expansion_candidate_count: int = Field(ge=0)
    observed_fact_count: Literal[0] = 0
    derived_measurement_count: Literal[0] = 0
    package_mutation_count: Literal[0] = 0
    mission_graph_mutation_count: Literal[0] = 0
    runtime_activation_count: Literal[0] = 0
    phase1_runtime_mutation_count: Literal[0] = 0
    phase2_writeback_count: Literal[0] = 0
    raw_gpx_payload_count: Literal[0] = 0


class AcceptedRouteNoteInterpretation(RouteNoteReviewedAssumptionModel):
    interpretation_id: str
    source_disposition_id: str
    source_route_note_candidate_id: str
    selected_disposition: Literal["promote_hint", "promote_warning"]
    interpretation_kind: Literal["ModelInterpretation"] = "ModelInterpretation"
    planning_assumption_status: Literal["accepted_by_admin"] = "accepted_by_admin"
    route_note_summary: str
    reviewer_alias: str
    decided_at: str
    observed_fact: Literal[False] = False
    derived_measurement: Literal[False] = False
    runtime_activation_allowed: Literal[False] = False


class RouteNoteLnExpansionCandidate(RouteNoteReviewedAssumptionModel):
    expansion_id: str
    source_interpretation_id: str
    source_route_note_candidate_id: str
    expansion_kind: Literal["hint_coverage", "warning_coverage"]
    proposed_coverage_label: str
    candidate_only: Literal[True] = True
    requires_final_runtime_policy: Literal[True] = True
    runtime_activation_allowed: Literal[False] = False
    package_mutation_allowed: Literal[False] = False
    mission_graph_mutation_allowed: Literal[False] = False


class RouteNoteFieldVerificationRequest(RouteNoteReviewedAssumptionModel):
    request_id: str
    source_disposition_id: str
    source_route_note_candidate_id: str
    reason: Literal["admin_requested_field_verify"] = "admin_requested_field_verify"
    runtime_activation_allowed: Literal[False] = False


class RouteNoteIgnoredDisposition(RouteNoteReviewedAssumptionModel):
    source_disposition_id: str
    source_route_note_candidate_id: str
    reason: Literal["admin_ignored_route_note"] = "admin_ignored_route_note"


class RouteNoteReviewedAssumptionSet(RouteNoteReviewedAssumptionModel):
    artifact_id: str
    artifact_kind: Literal["pretrip_route_note_reviewed_assumptions"] = (
        "pretrip_route_note_reviewed_assumptions"
    )
    project_id: str
    source_disposition_log_ref: str
    status: Literal["workspace_reviewed_planning_assumption_candidates"] = (
        "workspace_reviewed_planning_assumption_candidates"
    )
    accepted_interpretations: list[AcceptedRouteNoteInterpretation]
    ln_expansion_candidates: list[RouteNoteLnExpansionCandidate]
    field_verification_requests: list[RouteNoteFieldVerificationRequest]
    ignored_dispositions: list[RouteNoteIgnoredDisposition]
    counts: RouteNoteReviewedAssumptionCounts
    boundary: RouteNoteReviewedAssumptionBoundary = Field(
        default_factory=RouteNoteReviewedAssumptionBoundary
    )
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_boundary_and_counts(self) -> "RouteNoteReviewedAssumptionSet":
        if self.counts.accepted_interpretation_count != len(
            self.accepted_interpretations
        ):
            raise ValueError("accepted_interpretation_count must match records")
        if self.counts.ln_expansion_candidate_count != len(
            self.ln_expansion_candidates
        ):
            raise ValueError("ln_expansion_candidate_count must match records")
        if self.counts.field_verification_request_count != len(
            self.field_verification_requests
        ):
            raise ValueError("field_verification_request_count must match records")
        if self.counts.ignored_count != len(self.ignored_dispositions):
            raise ValueError("ignored_count must match records")
        _assert_no_raw_or_runtime_fragments(self.model_dump(mode="json"))
        return self

    def to_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n"


def build_route_note_reviewed_assumptions(
    disposition_log: RouteNoteDispositionLog,
    *,
    source_disposition_log_ref: str = DEFAULT_ROUTE_NOTE_DISPOSITION_LOG_REF,
) -> RouteNoteReviewedAssumptionSet:
    accepted = [
        _accepted_interpretation(record)
        for record in disposition_log.records
        if record.selected_disposition in {"promote_hint", "promote_warning"}
    ]
    expansions = [
        _ln_expansion_candidate(interpretation)
        for interpretation in accepted
    ]
    field_verify = [
        RouteNoteFieldVerificationRequest(
            request_id=f"route_note_field_verify.{record.candidate_ref}",
            source_disposition_id=record.disposition_id,
            source_route_note_candidate_id=record.candidate_ref,
        )
        for record in disposition_log.records
        if record.selected_disposition == "field_verify"
    ]
    ignored = [
        RouteNoteIgnoredDisposition(
            source_disposition_id=record.disposition_id,
            source_route_note_candidate_id=record.candidate_ref,
        )
        for record in disposition_log.records
        if record.selected_disposition == "ignore"
    ]
    expansion_kinds = Counter(expansion.expansion_kind for expansion in expansions)
    return RouteNoteReviewedAssumptionSet(
        artifact_id=f"route_note_reviewed_assumptions.{disposition_log.project_id}.v0",
        project_id=disposition_log.project_id,
        source_disposition_log_ref=source_disposition_log_ref,
        accepted_interpretations=accepted,
        ln_expansion_candidates=expansions,
        field_verification_requests=field_verify,
        ignored_dispositions=ignored,
        counts=RouteNoteReviewedAssumptionCounts(
            disposition_count=len(disposition_log.records),
            accepted_interpretation_count=len(accepted),
            ln_expansion_candidate_count=len(expansions),
            field_verification_request_count=len(field_verify),
            ignored_count=len(ignored),
            warning_expansion_candidate_count=expansion_kinds["warning_coverage"],
            hint_expansion_candidate_count=expansion_kinds["hint_coverage"],
        ),
        boundary=RouteNoteReviewedAssumptionBoundary(
            notes=[
                "Route-note dispositions can become reviewed planning assumptions only inside a copied workspace.",
                "Ln expansion records are candidates for future coverage only; they do not activate Phase 1 runtime warnings.",
                    "Route notes remain model interpretation planning assumptions, not observed fact or derived measurement records.",
            ],
        ),
        notes=[
            "promote_hint and promote_warning create accepted planning interpretation records.",
            "field_verify creates a field verification request; ignore is retained as an audit record.",
        ],
    )


def write_route_note_reviewed_assumptions_for_workspace(
    project_root: Path | str,
    *,
    disposition_log_ref: str = DEFAULT_ROUTE_NOTE_DISPOSITION_LOG_REF,
    output_ref: str = DEFAULT_ROUTE_NOTE_REVIEWED_ASSUMPTIONS_REF,
) -> RouteNoteReviewedAssumptionSet:
    workspace_root = _resolve_workspace_project_root(project_root)
    disposition_log = load_route_note_disposition_log(workspace_root / disposition_log_ref)
    assumption_set = build_route_note_reviewed_assumptions(
        disposition_log,
        source_disposition_log_ref=disposition_log_ref,
    )
    destination = workspace_root / output_ref
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(assumption_set.to_json(), encoding="utf-8")
    return assumption_set


def load_route_note_reviewed_assumptions(
    path: Path | str,
) -> RouteNoteReviewedAssumptionSet:
    return RouteNoteReviewedAssumptionSet.model_validate_json(
        Path(path).read_text(encoding="utf-8")
    )


def _accepted_interpretation(
    record: RouteNoteDispositionRecord,
) -> AcceptedRouteNoteInterpretation:
    return AcceptedRouteNoteInterpretation(
        interpretation_id=f"accepted_route_note_interpretation.{record.candidate_ref}",
        source_disposition_id=record.disposition_id,
        source_route_note_candidate_id=record.candidate_ref,
        selected_disposition=record.selected_disposition,
        route_note_summary=record.proposed_coverage_label,
        reviewer_alias=record.reviewer_alias,
        decided_at=record.decided_at,
    )


def _ln_expansion_candidate(
    interpretation: AcceptedRouteNoteInterpretation,
) -> RouteNoteLnExpansionCandidate:
    expansion_kind: Literal["hint_coverage", "warning_coverage"] = (
        "warning_coverage"
        if interpretation.selected_disposition == "promote_warning"
        else "hint_coverage"
    )
    return RouteNoteLnExpansionCandidate(
        expansion_id=f"ln_expansion_candidate.{interpretation.source_route_note_candidate_id}",
        source_interpretation_id=interpretation.interpretation_id,
        source_route_note_candidate_id=interpretation.source_route_note_candidate_id,
        expansion_kind=expansion_kind,
        proposed_coverage_label=f"route_note_{expansion_kind}",
    )


def _resolve_workspace_project_root(project_root: Path | str) -> Path:
    path = Path(project_root).resolve()
    if (path / "project.json").exists():
        project_path = path
    elif path.name == "project.json" and path.exists():
        project_path = path.parent
    else:
        raise FileNotFoundError(f"could not find workspace project.json under {path}")
    if _is_relative_to(project_path, REPO_FIXTURE_PROJECTS_ROOT.resolve()):
        raise ValueError("route-note reviewed assumptions must be written only to a copied workspace")
    return project_path


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _assert_no_raw_or_runtime_fragments(payload: Any) -> None:
    sanitized = _strip_allowed_boundary_keys(payload)
    serialized = json.dumps(sanitized, ensure_ascii=False, sort_keys=True).lower()
    for fragment in (
        "<" + "gpx",
        "<" + "trkpt",
        "raw_gpx",
        "raw_payload",
        "raw_samples",
        "." + "gpx",
        "pdrsample",
        "catographydata",
        "/" + "safety/",
        "phase1incidentbridge",
        "observedfact",
        "derivedmeasurement",
        "phase2brain",
        "runtime_activation_allowed\": true",
    ):
        if fragment in serialized:
            raise ValueError(f"forbidden route-note assumption fragment: {fragment}")


def _strip_allowed_boundary_keys(payload: Any) -> Any:
    if isinstance(payload, dict):
        return {
            key: _strip_allowed_boundary_keys(value)
            for key, value in payload.items()
            if key
            not in {
                "raw_gpx_embedded",
                "raw_gpx_payload_count",
                "observed_fact_created",
                "derived_measurement_created",
            }
        }
    if isinstance(payload, list):
        return [_strip_allowed_boundary_keys(item) for item in payload]
    return payload
