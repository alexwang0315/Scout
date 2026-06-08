from __future__ import annotations

import json
import os
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pretrip_review_decision_apply import (
    PreTripReviewDecisionApplyPlan,
    ReviewDecisionApplyItem,
    load_review_decision_apply_plan,
)
from pretrip_review_decision_log import ReviewDecision


DEFAULT_DEPARTURE_REVIEWED_CANDIDATES_REF = "outputs/departure_reviewed_candidates.json"


class StrictDepartureReviewedCandidateModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DepartureReviewedCandidate(StrictDepartureReviewedCandidateModel):
    candidate_ref: str
    decision: Literal["accepted", "corrected"]
    promotion_scope: Literal[
        "checkpoint_candidate",
        "departure_annotation_candidate",
        "planning_assumption_candidate",
    ]
    target_ids: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    summary: str
    correction_summary: str | None = None
    runtime_checkin_candidate: bool = False
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False
    human_review_required_before_runtime_use: Literal[True] = True


class DepartureReviewedCandidatesCounts(StrictDepartureReviewedCandidateModel):
    source_decision_count: int = Field(ge=0)
    promoted_candidate_count: int = Field(ge=0)
    accepted_count: int = Field(ge=0)
    corrected_count: int = Field(ge=0)
    rejected_audit_count: int = Field(ge=0)
    runtime_truth_count: Literal[0] = 0


class DepartureReviewedCandidatesBoundary(StrictDepartureReviewedCandidateModel):
    workspace_only: Literal[True] = True
    candidate_only: Literal[True] = True
    not_departure_approval: Literal[True] = True
    package_addendum_only: Literal[True] = True
    source_mutation_allowed: Literal[False] = False
    package_mutation_allowed: Literal[False] = False
    final_mission_graph_mutation_allowed: Literal[False] = False
    runtime_mutation_allowed: Literal[False] = False
    phase1_runtime_mutation_allowed: Literal[False] = False
    phase2_writeback_allowed: Literal[False] = False
    runtime_safety_truth: Literal[False] = False


class DepartureReviewedCandidatesPackage(StrictDepartureReviewedCandidateModel):
    artifact_id: str
    artifact_kind: Literal["pretrip_departure_reviewed_candidates"] = (
        "pretrip_departure_reviewed_candidates"
    )
    project_id: str
    source_apply_plan_ref: str
    candidates: list[DepartureReviewedCandidate]
    rejected_audit_refs: list[str] = Field(default_factory=list)
    counts: DepartureReviewedCandidatesCounts
    boundary: DepartureReviewedCandidatesBoundary = Field(
        default_factory=DepartureReviewedCandidatesBoundary
    )
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_boundary(self) -> "DepartureReviewedCandidatesPackage":
        if any(candidate.runtime_safety_truth for candidate in self.candidates):
            raise ValueError("departure reviewed candidates must not be runtime truth")
        if self.counts.runtime_truth_count != 0:
            raise ValueError("runtime truth count must stay zero")
        _assert_no_runtime_fragments(self.model_dump(mode="json"))
        return self

    def to_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n"


def build_departure_reviewed_candidates_from_apply_plan(
    *,
    project_id: str,
    source_apply_plan_ref: str,
    apply_plan: PreTripReviewDecisionApplyPlan,
) -> DepartureReviewedCandidatesPackage:
    candidates = [
        _candidate_from_apply_item(item)
        for item in apply_plan.decisions
        if item.decision in {ReviewDecision.ACCEPTED, ReviewDecision.CORRECTED}
    ]
    counts = Counter(candidate.decision for candidate in candidates)
    rejected_audit_refs = [
        item.candidate_ref
        for item in apply_plan.decisions
        if item.decision == ReviewDecision.REJECTED
    ]
    return DepartureReviewedCandidatesPackage(
        artifact_id=f"departure_reviewed_candidates.{project_id}.v0",
        project_id=project_id,
        source_apply_plan_ref=source_apply_plan_ref,
        candidates=candidates,
        rejected_audit_refs=rejected_audit_refs,
        counts=DepartureReviewedCandidatesCounts(
            source_decision_count=apply_plan.counts.decision_count,
            promoted_candidate_count=len(candidates),
            accepted_count=counts["accepted"],
            corrected_count=counts["corrected"],
            rejected_audit_count=len(rejected_audit_refs),
        ),
        notes=[
            "This artifact is a reviewed planning addendum for departure package evaluation.",
            "It does not approve departure, compile Final MissionGraph, call safety APIs, or create runtime safety truth.",
        ],
    )


def write_departure_reviewed_candidates_for_workspace(
    project_root: Path | str,
) -> DepartureReviewedCandidatesPackage:
    root = Path(project_root)
    project_path = root if root.name == "project.json" else root / "project.json"
    _require_file(project_path, "project.json")
    workspace_root = project_path.parent
    project = _load_json(project_path)
    project_id = _require_project_ref(project, "project_id")
    apply_plan_ref = _require_project_ref(
        project,
        "review_decision_apply_plan_ref",
        default="outputs/review_decision_apply_plan.json",
    )
    destination_ref = str(
        project.get(
            "departure_reviewed_candidates_ref",
            DEFAULT_DEPARTURE_REVIEWED_CANDIDATES_REF,
        )
    )
    _reject_absolute_or_parent_ref(destination_ref, "departure_reviewed_candidates_ref")

    apply_plan_path = workspace_root / apply_plan_ref
    destination = workspace_root / destination_ref
    _require_file(apply_plan_path, "review_decision_apply_plan_ref")
    _require_workspace_relative_path(destination, workspace_root, "departure_reviewed_candidates_ref")

    package = build_departure_reviewed_candidates_from_apply_plan(
        project_id=project_id,
        source_apply_plan_ref=apply_plan_ref,
        apply_plan=load_review_decision_apply_plan(apply_plan_path),
    )
    _replace_json(destination, package.to_json())
    return package


def _candidate_from_apply_item(
    item: ReviewDecisionApplyItem,
) -> DepartureReviewedCandidate:
    return DepartureReviewedCandidate(
        candidate_ref=item.candidate_ref,
        decision=item.decision.value,  # type: ignore[arg-type]
        promotion_scope=_promotion_scope(item),
        target_ids=item.target_ids,
        source_refs=item.source_refs,
        summary=item.summary,
        correction_summary=item.correction_summary,
        runtime_checkin_candidate=item.candidate_application_scope
        in {"package_candidate", "gis_perception_cp"},
    )


def _promotion_scope(
    item: ReviewDecisionApplyItem,
) -> Literal[
    "checkpoint_candidate",
    "departure_annotation_candidate",
    "planning_assumption_candidate",
]:
    if item.candidate_application_scope == "package_candidate":
        return "checkpoint_candidate"
    if item.candidate_application_scope == "gis_perception_cp":
        return "departure_annotation_candidate"
    return "planning_assumption_candidate"


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _require_project_ref(
    project: dict[str, Any],
    key: str,
    *,
    default: str | None = None,
) -> str:
    value = project.get(key, default)
    if not isinstance(value, str) or not value:
        raise ValueError(f"project.json missing required string field: {key}")
    _reject_absolute_or_parent_ref(value, key)
    return value


def _require_file(path: Path, label: str) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"missing required {label}: {path}")


def _require_workspace_relative_path(path: Path, workspace_root: Path, label: str) -> None:
    try:
        path.resolve().relative_to(workspace_root.resolve())
    except ValueError as exc:
        raise ValueError(f"{label} must resolve inside the project workspace") from exc


def _reject_absolute_or_parent_ref(value: str, label: str) -> None:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{label} must be a project-relative path")


def _replace_json(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as tmp_file:
            tmp_name = tmp_file.name
            tmp_file.write(payload)
            tmp_file.flush()
            os.fsync(tmp_file.fileno())
        os.replace(tmp_name, path)
    finally:
        if tmp_name and Path(tmp_name).exists():
            Path(tmp_name).unlink()


def _assert_no_runtime_fragments(payload: dict[str, Any]) -> None:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    for fragment in ["/safety", "SafetyRuntimeSession", "ObservedFact", "raw_payload"]:
        if fragment in serialized:
            raise ValueError(f"forbidden runtime fragment in departure reviewed candidates: {fragment}")
