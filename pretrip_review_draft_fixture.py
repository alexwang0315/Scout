from __future__ import annotations

import json
from collections import Counter
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


DEFAULT_CHILAI_PROJECT_REF = (
    "tests/fixtures/pretrip/projects/chilai_nanhua_day1/project.json"
)


class ReviewDraftCategory(StrEnum):
    CONTOUR = "contour"
    SEGMENT_POLICY = "segment_policy"
    POI_READINESS = "poi_readiness"


class ReviewDraftActionKind(StrEnum):
    REQUEST_HUMAN_NOTE = "request_human_note"
    PROPOSE_CANDIDATE_EDIT = "propose_candidate_edit"
    REQUEST_SUPPORTING_EVIDENCE = "request_supporting_evidence"


class StrictReviewDraftModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReviewDraftAction(StrictReviewDraftModel):
    action_id: str
    category: ReviewDraftCategory
    action_kind: ReviewDraftActionKind
    draft_state: Literal["draft"] = "draft"
    source_ref_key: str
    source_ref: str
    source_artifact_kind: str
    candidate_ref: str
    title: str
    summary: str
    proposed_fields: dict[str, Any] = Field(default_factory=dict)
    reviewer_prompt: str
    draft_only: Literal[True] = True
    decision_recorded: Literal[False] = False
    source_mutation_allowed: Literal[False] = False
    package_mutation_allowed: Literal[False] = False
    runtime_mutation_allowed: Literal[False] = False
    admin_api_integration: Literal[False] = False


class ReviewDraftCounts(StrictReviewDraftModel):
    action_count: int = Field(ge=0)
    category_counts: dict[str, int] = Field(default_factory=dict)
    source_ref_count: int = Field(ge=0)
    draft_action_count: int = Field(ge=0)
    mutation_action_count: int = Field(ge=0)


class ReviewDraftBoundary(StrictReviewDraftModel):
    draft_only: Literal[True] = True
    decisions_recorded: Literal[False] = False
    source_mutation_allowed: Literal[False] = False
    package_mutation_allowed: Literal[False] = False
    review_log_mutation_allowed: Literal[False] = False
    runtime_mutation_allowed: Literal[False] = False
    phase1_runtime_mutation_allowed: Literal[False] = False
    phase2_writeback_allowed: Literal[False] = False
    external_api_calls_made: Literal[False] = False
    admin_api_integration: Literal[False] = False
    raw_payloads_embedded: Literal[False] = False
    notes: list[str] = Field(default_factory=list)


class PreTripReviewDraftLog(StrictReviewDraftModel):
    log_id: str
    artifact_kind: Literal["pretrip_review_draft_log"] = "pretrip_review_draft_log"
    project_id: str
    status: Literal["draft_only"] = "draft_only"
    source_refs: list[str]
    actions: list[ReviewDraftAction]
    counts: ReviewDraftCounts
    boundary: ReviewDraftBoundary = Field(default_factory=ReviewDraftBoundary)
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_draft_boundary(self) -> "PreTripReviewDraftLog":
        if any(action.decision_recorded for action in self.actions):
            raise ValueError("review draft fixture must not record decisions")
        if any(action.source_mutation_allowed for action in self.actions):
            raise ValueError("review draft fixture must not mutate source artifacts")
        if any(action.package_mutation_allowed for action in self.actions):
            raise ValueError("review draft fixture must not mutate packages")
        if any(action.runtime_mutation_allowed for action in self.actions):
            raise ValueError("review draft fixture must not mutate runtime state")
        _assert_no_raw_payload_fragments(self.model_dump(mode="json"))
        return self

    def to_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n"


def build_chilai_review_draft_log(project_root: Path | str) -> PreTripReviewDraftLog:
    project_path = _resolve_chilai_project_path(Path(project_root))
    fixture_root = project_path.parent
    project = _load_json(project_path)

    actions = [
        _contour_action(fixture_root, project),
        _segment_policy_action(fixture_root, project),
        _poi_readiness_action(fixture_root, project),
    ]
    category_counts = Counter(action.category.value for action in actions)
    source_refs = _ordered_project_refs(
        project,
        [
            "contour_interpretation_candidates_ref",
            "segment_policy_candidates_ref",
            "poi_readiness_candidates_ref",
        ],
    )

    return PreTripReviewDraftLog(
        log_id=f"review_draft_log.{project['project_id']}.v0",
        project_id=project["project_id"],
        source_refs=source_refs,
        actions=actions,
        counts=ReviewDraftCounts(
            action_count=len(actions),
            category_counts=dict(sorted(category_counts.items())),
            source_ref_count=len(source_refs),
            draft_action_count=sum(1 for action in actions if action.draft_only),
            mutation_action_count=sum(
                1
                for action in actions
                if action.source_mutation_allowed
                or action.package_mutation_allowed
                or action.runtime_mutation_allowed
            ),
        ),
        boundary=ReviewDraftBoundary(
            notes=[
                "Draft output fixture only; it records proposed review actions, not decisions.",
                "Candidate artifacts, reviewed package outputs, review logs, and runtime stores remain read-only.",
                "No admin API, external API, package mutation, source mutation, or runtime mutation is performed.",
            ],
        ),
        notes=[
            "Representative Review Workflow slice C output for contour, segment policy, and POI readiness review drafts.",
            "Action payloads are compact pointers and proposed fields only; raw route, image, terrain, and sensor payloads are not embedded.",
        ],
    )


def load_review_draft_log(path: Path | str) -> PreTripReviewDraftLog:
    return PreTripReviewDraftLog.model_validate_json(
        Path(path).read_text(encoding="utf-8")
    )


def _contour_action(fixture_root: Path, project: dict[str, Any]) -> ReviewDraftAction:
    ref_key = "contour_interpretation_candidates_ref"
    ref = _required_project_ref(project, ref_key)
    payload = _load_json(fixture_root / ref)
    candidate = _first(payload.get("candidates", []), "contour candidate")
    candidate_id = str(candidate["candidate_id"])
    target_segments = list(candidate.get("target_refs", {}).get("segment_candidate_refs", []))
    return ReviewDraftAction(
        action_id=f"review_draft.{project['project_id']}.contour.{candidate_id}",
        category=ReviewDraftCategory.CONTOUR,
        action_kind=ReviewDraftActionKind.REQUEST_HUMAN_NOTE,
        source_ref_key=ref_key,
        source_ref=ref,
        source_artifact_kind="contour_interpretation_candidates",
        candidate_ref=candidate_id,
        title="Draft contour review note",
        summary="Ask reviewer to confirm whether close-contour concern should remain a candidate note.",
        proposed_fields={
            "candidate_ref": candidate_id,
            "target_segment_refs": target_segments,
            "review_note": "Confirm terrain concern from candidate metadata before it can influence planning.",
            "confidence_after_review": "human_review_required",
        },
        reviewer_prompt="Confirm or rewrite the contour note; do not attach raw image, terrain raster, or route payloads.",
    )


def _segment_policy_action(fixture_root: Path, project: dict[str, Any]) -> ReviewDraftAction:
    ref_key = "segment_policy_candidates_ref"
    ref = _required_project_ref(project, ref_key)
    payload = _load_json(fixture_root / ref)
    candidates = payload.get("candidates", [])
    candidate = next(
        (
            item
            for item in candidates
            if item.get("requirement", {}).get("retreat_available") is True
        ),
        _first(candidates, "segment policy candidate"),
    )
    candidate_id = str(candidate["candidate_id"])
    requirement = candidate.get("requirement", {})
    return ReviewDraftAction(
        action_id=f"review_draft.{project['project_id']}.segment_policy.{candidate_id}",
        category=ReviewDraftCategory.SEGMENT_POLICY,
        action_kind=ReviewDraftActionKind.PROPOSE_CANDIDATE_EDIT,
        source_ref_key=ref_key,
        source_ref=ref,
        source_artifact_kind=payload.get("artifact_kind", "segment_policy_candidates"),
        candidate_ref=candidate_id,
        title="Draft segment policy review edit",
        summary="Prepare a human-review draft for conservative daylight, water, camp, retreat, and signal assumptions.",
        proposed_fields={
            "segment_candidate_id": candidate.get("segment_candidate_id"),
            "requires_daylight": requirement.get("requires_daylight"),
            "water_available": requirement.get("water_available"),
            "camp_available": requirement.get("camp_available"),
            "retreat_available": requirement.get("retreat_available"),
            "signal_expected": requirement.get("signal_expected"),
            "review_state_after_edit": "proposed",
        },
        reviewer_prompt="Review these policy assumptions as draft fields only; do not compile them into MissionGraph runtime policy.",
    )


def _poi_readiness_action(fixture_root: Path, project: dict[str, Any]) -> ReviewDraftAction:
    ref_key = "poi_readiness_candidates_ref"
    ref = _required_project_ref(project, ref_key)
    payload = _load_json(fixture_root / ref)
    findings = payload.get("findings", [])
    finding = next(
        (
            item
            for item in findings
            if item.get("severity") == "blocker"
        ),
        findings[0] if findings else None,
    )
    if finding is not None:
        candidate_id = str(finding["candidate_id"])
        return ReviewDraftAction(
            action_id=f"review_draft.{project['project_id']}.poi_readiness.{candidate_id}",
            category=ReviewDraftCategory.POI_READINESS,
            action_kind=ReviewDraftActionKind.REQUEST_SUPPORTING_EVIDENCE,
            source_ref_key=ref_key,
            source_ref=ref,
            source_artifact_kind=payload.get("artifact_kind", "poi_readiness_candidates"),
            candidate_ref=candidate_id,
            title="Draft POI readiness evidence request",
            summary=str(finding.get("message", "POI readiness finding requires review.")),
            proposed_fields={
                "category": finding.get("category"),
                "severity": finding.get("severity"),
                "requested_review_output": "review POI corridor coverage evidence or keep candidate finding",
            },
            reviewer_prompt="Review the POI coverage finding as a draft only; do not embed source files.",
        )

    policy = _first(payload.get("policy_candidates", []), "POI readiness policy")
    category = str(policy.get("category", "route_corridor_poi_coverage"))
    candidate_id = f"poi_readiness_policy.{project['project_id']}.{category}"
    return ReviewDraftAction(
        action_id=f"review_draft.{project['project_id']}.poi_readiness.{candidate_id}",
        category=ReviewDraftCategory.POI_READINESS,
        action_kind=ReviewDraftActionKind.PROPOSE_CANDIDATE_EDIT,
        source_ref_key=ref_key,
        source_ref=ref,
        source_artifact_kind=payload.get("artifact_kind", "poi_readiness_candidates"),
        candidate_ref=candidate_id,
        title="Draft POI corridor coverage policy review",
        summary="Prepare admin review of the parameterized route-corridor POI coverage policy.",
        proposed_fields={
            "category": category,
            "severity": policy.get("severity"),
            "corridor_distance_m": policy.get("corridor_distance_m"),
            "minimum_poi_count": policy.get("minimum_poi_count"),
            "current_finding_count": payload.get("counts", {}).get("finding_candidate_count"),
            "route_corridor_poi_count": payload.get("counts", {}).get("route_corridor_poi_count"),
            "review_state_after_edit": "proposed",
        },
        reviewer_prompt="Review the POI corridor distance/count parameters as draft fields only; do not turn missing POI categories into blockers.",
    )


def _resolve_chilai_project_path(path: Path) -> Path:
    if path.is_file():
        return path
    if (path / "project.json").exists():
        return path / "project.json"
    candidate = path / DEFAULT_CHILAI_PROJECT_REF
    if candidate.exists():
        return candidate
    raise FileNotFoundError(f"could not find Chilai pretrip project.json under {path}")


def _required_project_ref(project: dict[str, Any], ref_key: str) -> str:
    ref = project.get(ref_key)
    if not ref:
        raise ValueError(f"project.json missing required review draft ref: {ref_key}")
    return str(ref)


def _ordered_project_refs(project: dict[str, Any], ref_keys: list[str]) -> list[str]:
    return [str(project[key]) for key in ref_keys if project.get(key)]


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _first(items: list[Any], label: str) -> Any:
    if not items:
        raise ValueError(f"missing {label}")
    return items[0]


def _assert_no_raw_payload_fragments(payload: dict[str, Any]) -> None:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    forbidden_fragments = [
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
        "sample_payload",
        "elevation_grid",
        "terrain_tile",
        "admin_api.py",
        "requests.",
        "httpx.",
    ]
    for fragment in forbidden_fragments:
        if fragment in serialized:
            raise ValueError(f"review draft fixture contains forbidden raw/runtime fragment: {fragment}")
