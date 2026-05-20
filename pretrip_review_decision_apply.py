from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pretrip_models import PreTripPackage
from pretrip_review_decision_log import (
    PreTripReviewDecisionLog,
    ReviewDecision,
    ReviewDecisionRecord,
    load_review_decision_log,
)


DEFAULT_CHILAI_PROJECT_REF = (
    "tests/fixtures/pretrip/projects/chilai_nanhua_day1/project.json"
)


class StrictDecisionApplyModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReviewDecisionApplyBoundary(StrictDecisionApplyModel):
    would_apply_only: Literal[True] = True
    source_mutation_allowed: Literal[False] = False
    package_mutation_allowed: Literal[False] = False
    runtime_mutation_allowed: Literal[False] = False
    phase1_runtime_mutation_allowed: Literal[False] = False
    phase2_writeback_allowed: Literal[False] = False
    compiles_mission_graph: Literal[False] = False
    raw_payloads_embedded: Literal[False] = False
    notes: list[str] = Field(default_factory=list)


class ReviewDecisionApplyCounts(StrictDecisionApplyModel):
    decision_count: int = Field(ge=0)
    accepted: int = Field(ge=0)
    corrected: int = Field(ge=0)
    rejected: int = Field(ge=0)
    source_ref_count: int = Field(ge=0)
    package_candidate_apply_count: int = Field(ge=0)
    runtime_mutation_count: Literal[0] = 0


class ReviewDecisionApplyItem(StrictDecisionApplyModel):
    decision_id: str
    draft_action_id: str
    decision: ReviewDecision
    candidate_ref: str
    target_ids: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    package_candidate_matches: list[str] = Field(default_factory=list)
    package_candidate_apply_count: int = Field(ge=0)
    summary: str
    correction_summary: str | None = None
    would_apply_to_package: bool = False
    notes: list[str] = Field(default_factory=list)


class PreTripReviewDecisionApplyPlan(StrictDecisionApplyModel):
    plan_id: str
    artifact_kind: Literal["pretrip_review_decision_apply_plan"] = (
        "pretrip_review_decision_apply_plan"
    )
    project_id: str
    review_decision_log_ref: str
    package_ref: str
    package_id: str
    package_status: str
    decisions: list[ReviewDecisionApplyItem]
    counts: ReviewDecisionApplyCounts
    boundary: ReviewDecisionApplyBoundary = Field(default_factory=ReviewDecisionApplyBoundary)
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_apply_plan_boundary(self) -> "PreTripReviewDecisionApplyPlan":
        if self.counts.runtime_mutation_count != 0:
            raise ValueError("review decision apply plan must not mutate runtime")
        if self.boundary.package_mutation_allowed:
            raise ValueError("review decision apply plan must not mutate packages")
        if self.boundary.compiles_mission_graph:
            raise ValueError("review decision apply plan must not compile MissionGraph")
        if self.counts.package_candidate_apply_count != sum(
            item.package_candidate_apply_count for item in self.decisions
        ):
            raise ValueError("package_candidate_apply_count does not match decisions")
        _assert_no_runtime_or_raw_payload_fragments(self.model_dump(mode="json"))
        return self

    def to_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n"


def build_chilai_review_decision_apply_plan(
    project_root: Path | str,
) -> PreTripReviewDecisionApplyPlan:
    project_path = _resolve_chilai_project_path(Path(project_root))
    fixture_root = project_path.parent
    project = _load_json(project_path)

    review_decision_log_ref = str(project["review_decision_log_ref"])
    package_ref = str(project["package_ref"])
    decision_log = load_review_decision_log(fixture_root / review_decision_log_ref)
    package = PreTripPackage.model_validate_json(
        (fixture_root / package_ref).read_text(encoding="utf-8")
    )

    return build_review_decision_apply_plan(
        project_id=str(project["project_id"]),
        review_decision_log_ref=review_decision_log_ref,
        package_ref=package_ref,
        decision_log=decision_log,
        package=package,
    )


def build_review_decision_apply_plan_from_paths(
    *,
    project_id: str,
    review_decision_log_path: Path | str,
    package_path: Path | str,
    review_decision_log_ref: str,
    package_ref: str,
) -> PreTripReviewDecisionApplyPlan:
    decision_log = load_review_decision_log(review_decision_log_path)
    package = PreTripPackage.model_validate_json(
        Path(package_path).read_text(encoding="utf-8")
    )

    return build_review_decision_apply_plan(
        project_id=project_id,
        review_decision_log_ref=review_decision_log_ref,
        package_ref=package_ref,
        decision_log=decision_log,
        package=package,
    )


def build_review_decision_apply_plan(
    *,
    project_id: str,
    review_decision_log_ref: str,
    package_ref: str,
    decision_log: PreTripReviewDecisionLog,
    package: PreTripPackage,
) -> PreTripReviewDecisionApplyPlan:
    package_candidate_ids = _package_candidate_ids(package)
    decisions = [
        _apply_item(decision, package_candidate_ids=package_candidate_ids)
        for decision in decision_log.decisions
    ]
    counts_by_decision = Counter(item.decision.value for item in decisions)
    source_refs = sorted(
        source_ref
        for item in decisions
        for source_ref in item.source_refs
    )

    return PreTripReviewDecisionApplyPlan(
        plan_id=f"review_decision_apply_plan.{project_id}.v0",
        project_id=project_id,
        review_decision_log_ref=review_decision_log_ref,
        package_ref=package_ref,
        package_id=package.package_id,
        package_status=package.status,
        decisions=decisions,
        counts=ReviewDecisionApplyCounts(
            decision_count=len(decisions),
            accepted=counts_by_decision["accepted"],
            corrected=counts_by_decision["corrected"],
            rejected=counts_by_decision["rejected"],
            source_ref_count=len(set(source_refs)),
            package_candidate_apply_count=sum(
                item.package_candidate_apply_count for item in decisions
            ),
        ),
        boundary=ReviewDecisionApplyBoundary(
            notes=[
                "Decision apply plan is a deterministic local planning artifact only.",
                "It records what the append-only review decisions point at without mutating source artifacts, PreTripPackage, runtime state, Phase 2 Brain state, or MissionGraph outputs.",
                "Current decision candidate refs are contour, segment-policy, and POI-readiness candidates, not direct PreTripPackage candidate ids.",
            ],
        ),
        notes=[
            "Package application count is based on direct decision candidate_ref matches in PreTripPackage candidate collections.",
            "Decision target_ids remain recorded as review references and are not treated as package patches by this artifact.",
        ],
    )


def load_review_decision_apply_plan(path: Path | str) -> PreTripReviewDecisionApplyPlan:
    return PreTripReviewDecisionApplyPlan.model_validate_json(
        Path(path).read_text(encoding="utf-8")
    )


def write_chilai_review_decision_apply_plan(
    project_root: Path | str,
    output_path: Path | str | None = None,
) -> PreTripReviewDecisionApplyPlan:
    project_path = _resolve_chilai_project_path(Path(project_root))
    plan = build_chilai_review_decision_apply_plan(project_path)
    destination = Path(output_path) if output_path is not None else (
        project_path.parent / "outputs" / "review_decision_apply_plan.json"
    )
    destination.write_text(plan.to_json(), encoding="utf-8")
    return plan


def _apply_item(
    decision: ReviewDecisionRecord,
    *,
    package_candidate_ids: set[str],
) -> ReviewDecisionApplyItem:
    package_matches = (
        [decision.candidate_ref]
        if decision.candidate_ref in package_candidate_ids
        else []
    )
    source_refs = sorted(
        {
            source_ref.source_ref
            for source_ref in decision.source_review_queue_item_refs
        }
    )
    return ReviewDecisionApplyItem(
        decision_id=decision.decision_id,
        draft_action_id=decision.draft_action_id,
        decision=decision.decision,
        candidate_ref=decision.candidate_ref,
        target_ids=list(decision.target_ids),
        source_refs=source_refs,
        package_candidate_matches=package_matches,
        package_candidate_apply_count=len(package_matches),
        summary=decision.summary,
        correction_summary=(
            decision.correction.summary if decision.correction is not None else None
        ),
        would_apply_to_package=bool(package_matches),
        notes=[
            "No direct PreTripPackage candidate match; retained as a decision pointer only."
            if not package_matches
            else "Direct PreTripPackage candidate match detected; this artifact still does not mutate it."
        ],
    )


def _package_candidate_ids(package: PreTripPackage) -> set[str]:
    ids: set[str] = set()
    for collection in (
        package.checkpoint_candidates,
        package.segment_candidates,
        package.retreat_route_candidates,
        package.route_guide_timing_candidates,
    ):
        for candidate in collection:
            ids.add(candidate.candidate_id)
    return ids


def _resolve_chilai_project_path(path: Path) -> Path:
    if path.name == "project.json":
        return path
    if (path / "project.json").exists():
        return path / "project.json"
    repo_fixture = path / DEFAULT_CHILAI_PROJECT_REF
    if repo_fixture.exists():
        return repo_fixture
    raise FileNotFoundError(f"could not find Chilai pretrip project.json under {path}")


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _assert_no_runtime_or_raw_payload_fragments(payload: Any) -> None:
    sanitized = _strip_allowed_boundary_keys(payload)
    serialized = json.dumps(sanitized, ensure_ascii=False, sort_keys=True)
    forbidden_fragments = (
        "/safety",
        "Phase1IncidentBridge",
        "SCOUT_PHASE2_INCIDENT_BRIDGE",
        "<trkpt",
        '"coordinates"',
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
        "source_payload",
        "raw_payload",
        "elevation_grid",
        "terrain_tile",
        "payload_fragment",
        "admin_api.py",
        "requests.",
        "httpx.",
    )
    for fragment in forbidden_fragments:
        if fragment.lower() in serialized.lower():
            raise ValueError(f"forbidden runtime/raw payload fragment: {fragment}")


def _strip_allowed_boundary_keys(payload: Any) -> Any:
    if isinstance(payload, dict):
        return {
            key: _strip_allowed_boundary_keys(value)
            for key, value in payload.items()
            if key != "raw_payloads_embedded"
        }
    if isinstance(payload, list):
        return [_strip_allowed_boundary_keys(item) for item in payload]
    return payload
