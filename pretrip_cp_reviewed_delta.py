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


DEFAULT_CP_REVIEWED_DELTA_REF = "outputs/cp_reviewed_delta.json"
DEFAULT_APPLY_PLAN_REF = "outputs/review_decision_apply_plan.json"

CpReviewedDeltaOperation = Literal[
    "record_accepted_cp_delta",
    "record_corrected_cp_delta",
]
CpReviewedDeltaScope = Literal[
    "checkpoint_candidate",
    "gis_perception_cp",
    "planning_assumption_cp",
]


class StrictCpDeltaModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CpReviewedDeltaRollbackAction(StrictCpDeltaModel):
    operation: Literal["remove_delta_action"] = "remove_delta_action"
    target_action_id: str
    reason: str
    runtime_mutation_allowed: Literal[False] = False


class CpReviewedDeltaAction(StrictCpDeltaModel):
    action_id: str
    decision_id: str
    decision: Literal["accepted", "corrected"]
    operation: CpReviewedDeltaOperation
    delta_scope: CpReviewedDeltaScope
    candidate_ref: str
    target_ids: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    summary: str
    correction_summary: str | None = None
    rollback_action: CpReviewedDeltaRollbackAction
    reversible: Literal[True] = True
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False
    package_mutation_allowed: Literal[False] = False
    runtime_mutation_allowed: Literal[False] = False

    @model_validator(mode="after")
    def enforce_rollback_target(self) -> "CpReviewedDeltaAction":
        if self.rollback_action.target_action_id != self.action_id:
            raise ValueError("rollback action must target the delta action")
        return self


class CpReviewedDeltaCounts(StrictCpDeltaModel):
    source_decision_count: int = Field(ge=0)
    action_count: int = Field(ge=0)
    accepted_count: int = Field(ge=0)
    corrected_count: int = Field(ge=0)
    rejected_audit_count: int = Field(ge=0)
    checkpoint_candidate_delta_count: int = Field(ge=0)
    gis_perception_delta_count: int = Field(ge=0)
    planning_assumption_delta_count: int = Field(ge=0)
    package_mutation_count: Literal[0] = 0
    runtime_mutation_count: Literal[0] = 0
    phase1_runtime_mutation_count: Literal[0] = 0


class CpReviewedDeltaBoundary(StrictCpDeltaModel):
    workspace_only: Literal[True] = True
    candidate_only: Literal[True] = True
    reversible: Literal[True] = True
    delta_artifact_only: Literal[True] = True
    source_mutation_allowed: Literal[False] = False
    package_mutation_allowed: Literal[False] = False
    final_mission_graph_mutation_allowed: Literal[False] = False
    runtime_mutation_allowed: Literal[False] = False
    phase1_runtime_mutation_allowed: Literal[False] = False
    phase2_writeback_allowed: Literal[False] = False
    runtime_safety_truth: Literal[False] = False
    live_safety_api_calls_allowed: Literal[False] = False
    notes: list[str] = Field(default_factory=list)


class PreTripCpReviewedDelta(StrictCpDeltaModel):
    delta_id: str
    artifact_kind: Literal["pretrip_cp_reviewed_delta"] = "pretrip_cp_reviewed_delta"
    project_id: str
    source_apply_plan_ref: str
    actions: list[CpReviewedDeltaAction]
    rejected_audit_refs: list[str] = Field(default_factory=list)
    counts: CpReviewedDeltaCounts
    boundary: CpReviewedDeltaBoundary = Field(default_factory=CpReviewedDeltaBoundary)
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_boundary(self) -> "PreTripCpReviewedDelta":
        if self.counts.action_count != len(self.actions):
            raise ValueError("action_count must match actions")
        if any(action.runtime_safety_truth for action in self.actions):
            raise ValueError("CP reviewed delta actions must not be runtime truth")
        if self.boundary.runtime_mutation_allowed:
            raise ValueError("CP reviewed delta must not mutate runtime")
        if self.boundary.package_mutation_allowed:
            raise ValueError("CP reviewed delta must not mutate packages")
        _assert_no_runtime_fragments(self.model_dump(mode="json"))
        return self

    def to_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n"


def build_cp_reviewed_delta_from_apply_plan(
    *,
    project_id: str,
    source_apply_plan_ref: str,
    apply_plan: PreTripReviewDecisionApplyPlan,
) -> PreTripCpReviewedDelta:
    actions = [
        _action_from_apply_item(project_id=project_id, item=item, index=index)
        for index, item in enumerate(apply_plan.decisions, start=1)
        if item.decision in {ReviewDecision.ACCEPTED, ReviewDecision.CORRECTED}
    ]
    rejected_audit_refs = [
        item.candidate_ref
        for item in apply_plan.decisions
        if item.decision == ReviewDecision.REJECTED
    ]
    by_decision = Counter(action.decision for action in actions)
    by_scope = Counter(action.delta_scope for action in actions)
    return PreTripCpReviewedDelta(
        delta_id=f"cp_reviewed_delta.{project_id}.v0",
        project_id=project_id,
        source_apply_plan_ref=source_apply_plan_ref,
        actions=actions,
        rejected_audit_refs=rejected_audit_refs,
        counts=CpReviewedDeltaCounts(
            source_decision_count=apply_plan.counts.decision_count,
            action_count=len(actions),
            accepted_count=by_decision["accepted"],
            corrected_count=by_decision["corrected"],
            rejected_audit_count=len(rejected_audit_refs),
            checkpoint_candidate_delta_count=by_scope["checkpoint_candidate"],
            gis_perception_delta_count=by_scope["gis_perception_cp"],
            planning_assumption_delta_count=by_scope["planning_assumption_cp"],
        ),
        boundary=CpReviewedDeltaBoundary(
            notes=[
                "CP reviewed delta is a reversible local planning artifact only.",
                "It records accepted/corrected review decisions as delta actions without mutating checkpoint candidates, packages, MissionGraph outputs, or runtime state.",
            ],
        ),
        notes=[
            "Rejected decisions are retained as audit refs and do not produce delta actions.",
            "A later reviewed package compiler may consume this artifact after explicit review.",
        ],
    )


def build_cp_reviewed_delta_for_workspace(
    project_root: Path | str,
    *,
    apply_plan_path: Path | str | None = None,
) -> PreTripCpReviewedDelta:
    root = Path(project_root)
    project_path = root if root.name == "project.json" else root / "project.json"
    workspace_root = project_path.parent
    project = _load_json(project_path)
    project_id = _require_project_ref(project, "project_id")
    resolved_apply_plan_path, source_apply_plan_ref = _resolve_apply_plan_path(
        workspace_root,
        project,
        apply_plan_path=apply_plan_path,
    )
    return build_cp_reviewed_delta_from_apply_plan(
        project_id=project_id,
        source_apply_plan_ref=source_apply_plan_ref,
        apply_plan=load_review_decision_apply_plan(resolved_apply_plan_path),
    )


def write_cp_reviewed_delta_for_workspace(
    project_root: Path | str,
    *,
    apply_plan_path: Path | str | None = None,
    output_ref: str | None = None,
) -> tuple[PreTripCpReviewedDelta, Path]:
    root = Path(project_root)
    project_path = root if root.name == "project.json" else root / "project.json"
    workspace_root = project_path.parent
    project = _load_json(project_path)
    project_id = _require_project_ref(project, "project_id")
    resolved_apply_plan_path, source_apply_plan_ref = _resolve_apply_plan_path(
        workspace_root,
        project,
        apply_plan_path=apply_plan_path,
    )
    destination_ref = output_ref or str(
        project.get("cp_reviewed_delta_ref", DEFAULT_CP_REVIEWED_DELTA_REF)
    )
    _reject_absolute_or_parent_ref(destination_ref, "cp_reviewed_delta_ref")
    destination = workspace_root / destination_ref
    _require_workspace_relative_path(destination, workspace_root, "cp_reviewed_delta_ref")
    delta = build_cp_reviewed_delta_from_apply_plan(
        project_id=project_id,
        source_apply_plan_ref=source_apply_plan_ref,
        apply_plan=load_review_decision_apply_plan(resolved_apply_plan_path),
    )
    _replace_json(destination, delta.to_json())
    return delta, destination


def _action_from_apply_item(
    *,
    project_id: str,
    item: ReviewDecisionApplyItem,
    index: int,
) -> CpReviewedDeltaAction:
    action_id = f"cp_reviewed_delta.{project_id}.{index:04d}"
    return CpReviewedDeltaAction(
        action_id=action_id,
        decision_id=item.decision_id,
        decision=item.decision.value,  # type: ignore[arg-type]
        operation=(
            "record_corrected_cp_delta"
            if item.decision == ReviewDecision.CORRECTED
            else "record_accepted_cp_delta"
        ),
        delta_scope=_delta_scope(item),
        candidate_ref=item.candidate_ref,
        target_ids=list(item.target_ids),
        source_refs=list(item.source_refs),
        summary=item.summary,
        correction_summary=item.correction_summary,
        rollback_action=CpReviewedDeltaRollbackAction(
            target_action_id=action_id,
            reason="Remove this planning delta action from the CP reviewed delta artifact.",
        ),
    )


def _delta_scope(item: ReviewDecisionApplyItem) -> CpReviewedDeltaScope:
    if item.candidate_application_scope == "package_candidate":
        return "checkpoint_candidate"
    if item.candidate_application_scope == "gis_perception_cp":
        return "gis_perception_cp"
    return "planning_assumption_cp"


def _resolve_apply_plan_path(
    workspace_root: Path,
    project: dict[str, Any],
    *,
    apply_plan_path: Path | str | None,
) -> tuple[Path, str]:
    if apply_plan_path is not None:
        path = Path(apply_plan_path)
        if not path.is_absolute():
            path = workspace_root / path
        _require_file(path, "apply_plan_path")
        source_ref = _source_ref_for_path(path, workspace_root)
        return path, source_ref
    apply_plan_ref = _require_project_ref(
        project,
        "review_decision_apply_plan_ref",
        default=DEFAULT_APPLY_PLAN_REF,
    )
    path = workspace_root / apply_plan_ref
    _require_file(path, "review_decision_apply_plan_ref")
    return path, apply_plan_ref


def _source_ref_for_path(path: Path, workspace_root: Path) -> str:
    try:
        return str(path.resolve().relative_to(workspace_root.resolve()))
    except ValueError:
        return str(path)


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


def _assert_no_runtime_fragments(payload: Any) -> None:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    forbidden_fragments = (
        "/safety",
        "Phase1IncidentBridge",
        "SCOUT_PHASE2_INCIDENT_BRIDGE",
        "PdrSample",
        "incident_samples",
        "raw_samples",
        "source_payload",
        "raw_payload",
        "admin_api.py",
        "requests.",
        "httpx.",
    )
    for fragment in forbidden_fragments:
        if fragment.lower() in serialized.lower():
            raise ValueError(f"forbidden runtime/raw payload fragment: {fragment}")
