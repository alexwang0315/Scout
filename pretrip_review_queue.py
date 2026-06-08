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


class ReviewQueueCategory(StrEnum):
    PLAN_VALIDATION = "plan_validation"
    POI_READINESS = "poi_readiness"
    SEGMENT_POLICY = "segment_policy"
    WEATHER_DAYLIGHT = "weather_daylight"
    CONTOUR_INTERPRETATION = "contour_interpretation"
    ROUTE_NOTE = "route_note"
    RUNTIME_HANDOFF = "runtime_handoff"
    DEPARTURE_BUNDLE = "departure_bundle"


class StrictReviewQueueModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReviewQueueItem(StrictReviewQueueModel):
    item_id: str
    category: ReviewQueueCategory
    source_ref_key: str
    source_ref: str
    source_artifact_kind: str
    candidate_ref: str
    severity: Literal["review", "warning", "blocker"]
    title: str
    summary: str
    candidate_only: Literal[True] = True
    human_review_required: Literal[True] = True
    decision_recorded: Literal[False] = False
    accept_reject_allowed: Literal[False] = False
    mutation_allowed: Literal[False] = False
    review_focus: list[str] = Field(default_factory=list)
    evidence_summary: dict[str, Any] = Field(default_factory=dict)


class ReviewQueueCounts(StrictReviewQueueModel):
    item_count: int = Field(ge=0)
    warning_count: int = Field(ge=0)
    blocker_count: int = Field(ge=0)
    review_count: int = Field(ge=0)
    source_ref_count: int = Field(ge=0)
    category_counts: dict[str, int] = Field(default_factory=dict)


class ReviewQueueBoundary(StrictReviewQueueModel):
    candidate_queue_only: Literal[True] = True
    decisions_recorded: Literal[False] = False
    accepts_candidates: Literal[False] = False
    rejects_candidates: Literal[False] = False
    package_mutation_allowed: Literal[False] = False
    review_log_mutation_allowed: Literal[False] = False
    runtime_mutation_allowed: Literal[False] = False
    phase1_runtime_mutation_allowed: Literal[False] = False
    phase2_writeback_allowed: Literal[False] = False
    external_api_calls_made: Literal[False] = False
    raw_payloads_embedded: Literal[False] = False
    ui_included: Literal[False] = False
    notes: list[str] = Field(default_factory=list)


class PreTripReviewQueueManifest(StrictReviewQueueModel):
    manifest_id: str
    artifact_kind: Literal["pretrip_review_queue_manifest"] = (
        "pretrip_review_queue_manifest"
    )
    project_id: str
    status: Literal["candidate_review_queue_only"] = "candidate_review_queue_only"
    source_refs: list[str]
    items: list[ReviewQueueItem]
    counts: ReviewQueueCounts
    boundary: ReviewQueueBoundary = Field(default_factory=ReviewQueueBoundary)
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_candidate_queue_boundary(self) -> "PreTripReviewQueueManifest":
        if any(item.decision_recorded for item in self.items):
            raise ValueError("review queue must not record decisions")
        if any(item.accept_reject_allowed for item in self.items):
            raise ValueError("review queue must not accept or reject candidates")
        if any(item.mutation_allowed for item in self.items):
            raise ValueError("review queue items must not mutate source artifacts")
        _assert_no_raw_or_runtime_fragments(self.model_dump(mode="json"))
        return self

    def to_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n"


def build_chilai_review_queue_manifest(
    project_root: Path | str,
) -> PreTripReviewQueueManifest:
    project_path = _resolve_chilai_project_path(Path(project_root))
    fixture_root = project_path.parent
    project = _load_json(project_path)

    items: list[ReviewQueueItem] = []
    items.extend(_plan_validation_items(fixture_root, project))
    items.extend(_poi_readiness_items(fixture_root, project))
    items.extend(_segment_policy_items(fixture_root, project))
    items.extend(_weather_daylight_items(fixture_root, project))
    items.extend(_contour_interpretation_items(fixture_root, project))
    items.extend(_route_note_items(fixture_root, project))
    items.extend(_runtime_handoff_items(fixture_root, project))
    items.extend(_departure_bundle_items(fixture_root, project))
    items.sort(key=lambda item: (item.category.value, item.item_id))

    category_counts = Counter(item.category.value for item in items)
    source_refs = _ordered_existing_refs(
        project,
        [
            "plan_validation_candidates_ref",
            "poi_readiness_candidates_ref",
            "segment_policy_candidates_ref",
            "weather_daylight_evidence_ref",
            "contour_interpretation_candidates_ref",
            "route_note_candidates_ref",
            "runtime_handoff_metadata_ref",
            "departure_bundle_manifest_ref",
        ],
    )

    return PreTripReviewQueueManifest(
        manifest_id=f"review_queue.{project['project_id']}.v0",
        project_id=project["project_id"],
        source_refs=source_refs,
        items=items,
        counts=ReviewQueueCounts(
            item_count=len(items),
            warning_count=sum(1 for item in items if item.severity == "warning"),
            blocker_count=sum(1 for item in items if item.severity == "blocker"),
            review_count=sum(1 for item in items if item.severity == "review"),
            source_ref_count=len(source_refs),
            category_counts=dict(sorted(category_counts.items())),
        ),
        boundary=ReviewQueueBoundary(
            notes=[
                "Queue manifest only; it records no accept/reject decisions.",
                "Source package, reviews, runtime handoff, departure bundle, and live runtime stores are read-only inputs.",
                "No UI, external API call, package mutation, review-log mutation, or runtime mutation is performed.",
            ],
        ),
        notes=[
            "Candidate-only Phase 4 human review queue manifest.",
            "Items are compact pointers to existing Chilai fixture candidate artifacts.",
            "Reviewers must use separate review tooling to accept, reject, or edit candidates.",
        ],
    )


def load_review_queue_manifest(path: Path | str) -> PreTripReviewQueueManifest:
    return PreTripReviewQueueManifest.model_validate_json(
        Path(path).read_text(encoding="utf-8")
    )


def _plan_validation_items(
    fixture_root: Path,
    project: dict[str, Any],
) -> list[ReviewQueueItem]:
    ref_key = "plan_validation_candidates_ref"
    ref = _required_project_ref(project, ref_key)
    payload = _load_json(fixture_root / ref)
    items: list[ReviewQueueItem] = []
    for finding in payload.get("findings", []):
        severity = finding.get("severity")
        if severity not in {"warning", "blocker"}:
            continue
        candidate_id = str(finding["candidate_id"])
        items.append(
            ReviewQueueItem(
                item_id=f"review_queue.{project['project_id']}.plan_validation.{candidate_id}",
                category=ReviewQueueCategory.PLAN_VALIDATION,
                source_ref_key=ref_key,
                source_ref=ref,
                source_artifact_kind=payload.get("artifact_kind", "plan_validation_candidates"),
                candidate_ref=candidate_id,
                severity=severity,
                title=f"Plan validation {severity}: {finding.get('rule_id', candidate_id)}",
                summary=str(finding.get("message", "")),
                review_focus=list(finding.get("missing_any", [])),
                evidence_summary={
                    "rule_id": finding.get("rule_id"),
                    "source_artifact_kind": finding.get("source_artifact_kind"),
                    "candidate_only": finding.get("candidate_only"),
                },
            )
        )
    return items


def _poi_readiness_items(
    fixture_root: Path,
    project: dict[str, Any],
) -> list[ReviewQueueItem]:
    ref_key = "poi_readiness_candidates_ref"
    ref = _required_project_ref(project, ref_key)
    payload = _load_json(fixture_root / ref)
    items: list[ReviewQueueItem] = []
    for finding in payload.get("findings", []):
        severity = finding.get("severity")
        if severity not in {"warning", "blocker"}:
            continue
        candidate_id = str(finding["candidate_id"])
        items.append(
            ReviewQueueItem(
                item_id=f"review_queue.{project['project_id']}.poi_readiness.{candidate_id}",
                category=ReviewQueueCategory.POI_READINESS,
                source_ref_key=ref_key,
                source_ref=ref,
                source_artifact_kind=payload.get("artifact_kind", "poi_readiness_candidates"),
                candidate_ref=candidate_id,
                severity=severity,
                title=f"POI readiness {severity}: {finding.get('category', candidate_id)}",
                summary=str(finding.get("message", "")),
                review_focus=list(finding.get("missing_any", [])),
                evidence_summary={
                    "category": finding.get("category"),
                    "candidate_only": finding.get("candidate_only"),
                    "present_category_count": len(
                        finding.get("evidence", {}).get("present_categories", [])
                    ),
                },
            )
        )
    return items


def _segment_policy_items(
    fixture_root: Path,
    project: dict[str, Any],
) -> list[ReviewQueueItem]:
    ref_key = "segment_policy_candidates_ref"
    ref = _required_project_ref(project, ref_key)
    payload = _load_json(fixture_root / ref)
    items: list[ReviewQueueItem] = []
    for candidate in payload.get("candidates", []):
        if candidate.get("human_review_required") is not True:
            continue
        candidate_id = str(candidate["candidate_id"])
        requirement = candidate.get("requirement", {})
        focus = [
            name
            for name, enabled in [
                ("daylight_required", requirement.get("requires_daylight")),
                ("water_unavailable", requirement.get("water_available") is False),
                ("camp_unavailable", requirement.get("camp_available") is False),
                ("retreat_unavailable", requirement.get("retreat_available") is False),
                ("signal_unexpected", requirement.get("signal_expected") is False),
            ]
            if enabled
        ]
        items.append(
            ReviewQueueItem(
                item_id=f"review_queue.{project['project_id']}.segment_policy.{candidate_id}",
                category=ReviewQueueCategory.SEGMENT_POLICY,
                source_ref_key=ref_key,
                source_ref=ref,
                source_artifact_kind=payload.get("artifact_kind", "segment_policy_candidates"),
                candidate_ref=candidate_id,
                severity="review",
                title=f"Segment policy review: {candidate.get('segment_candidate_id', candidate_id)}",
                summary=str(candidate.get("notes", "Human review required.")),
                review_focus=focus,
                evidence_summary={
                    "segment_candidate_id": candidate.get("segment_candidate_id"),
                    "from_candidate_id": candidate.get("from_candidate_id"),
                    "to_candidate_id": candidate.get("to_candidate_id"),
                    "review_state": candidate.get("review_state"),
                    "compile_boundary": candidate.get("compile_boundary"),
                    "expected_duration_seconds": requirement.get("expected_duration_seconds"),
                },
            )
        )
    return items


def _weather_daylight_items(
    fixture_root: Path,
    project: dict[str, Any],
) -> list[ReviewQueueItem]:
    ref_key = "weather_daylight_evidence_ref"
    ref = _required_project_ref(project, ref_key)
    payload = _load_json(fixture_root / ref)
    validation = payload.get("validation", {})
    daylight = payload.get("daylight", {})
    weather_window = payload.get("weather_window", {})
    is_placeholder = (
        payload.get("human_review_required") is True
        or validation.get("staleness") == "placeholder"
        or daylight.get("source_status") == "manual_placeholder"
        or weather_window.get("source_status") == "manual_placeholder"
    )
    if not is_placeholder:
        return []
    return [
        ReviewQueueItem(
            item_id=f"review_queue.{project['project_id']}.weather_daylight.{payload.get('evidence_id', 'placeholder')}",
            category=ReviewQueueCategory.WEATHER_DAYLIGHT,
            source_ref_key=ref_key,
            source_ref=ref,
            source_artifact_kind="weather_daylight_evidence",
            candidate_ref=str(payload.get("evidence_id", ref)),
            severity="warning",
            title="Weather/daylight placeholder review",
            summary="Weather and daylight fields are placeholder-only and require human review before go/no-go use.",
            review_focus=["reviewed_weather_window", "reviewed_daylight_window"],
            evidence_summary={
                "validation_status": validation.get("validation_status"),
                "staleness": validation.get("staleness"),
                "daylight_source_status": daylight.get("source_status"),
                "weather_source_status": weather_window.get("source_status"),
                "external_api_calls_made": payload.get("external_api_calls_made"),
            },
        )
    ]


def _contour_interpretation_items(
    fixture_root: Path,
    project: dict[str, Any],
) -> list[ReviewQueueItem]:
    ref_key = "contour_interpretation_candidates_ref"
    ref = _required_project_ref(project, ref_key)
    payload = _load_json(fixture_root / ref)
    items: list[ReviewQueueItem] = []
    for candidate in payload.get("candidates", []):
        if candidate.get("human_review_required") is not True:
            continue
        candidate_id = str(candidate["candidate_id"])
        items.append(
            ReviewQueueItem(
                item_id=f"review_queue.{project['project_id']}.contour.{candidate_id}",
                category=ReviewQueueCategory.CONTOUR_INTERPRETATION,
                source_ref_key=ref_key,
                source_ref=ref,
                source_artifact_kind="contour_interpretation_candidates",
                candidate_ref=candidate_id,
                severity="review",
                title=f"Contour interpretation review: {candidate_id}",
                summary=str(candidate.get("notes", "Contour interpretation requires review.")),
                review_focus=list(candidate.get("target_refs", {}).get("segment_candidate_refs", [])),
                evidence_summary={
                    "status": candidate.get("status"),
                    "confidence": candidate.get("confidence"),
                    "interpretation_mode": candidate.get("interpretation_mode"),
                    "not_observed_fact": candidate.get("not_observed_fact"),
                    "source_artifact_refs": candidate.get("source_artifact_refs", {}),
                },
            )
        )
    return items


def _route_note_items(
    fixture_root: Path,
    project: dict[str, Any],
) -> list[ReviewQueueItem]:
    ref_key = "route_note_candidates_ref"
    ref = _required_project_ref(project, ref_key)
    payload = _load_json(fixture_root / ref)
    items: list[ReviewQueueItem] = []
    for candidate in payload.get("candidates", []):
        if candidate.get("potential_ln_signal") is not True:
            continue
        candidate_id = str(candidate["candidate_id"])
        category = str(candidate.get("note_category", "uncategorized_note"))
        severity: Literal["review", "warning", "blocker"] = (
            "warning" if category == "hazard_hint" else "review"
        )
        items.append(
            ReviewQueueItem(
                item_id=f"review_queue.{project['project_id']}.route_note.{candidate_id}",
                category=ReviewQueueCategory.ROUTE_NOTE,
                source_ref_key=ref_key,
                source_ref=ref,
                source_artifact_kind=payload.get("artifact_kind", "pretrip_route_note_candidates"),
                candidate_ref=candidate_id,
                severity=severity,
                title=f"Route note Ln proposal review: {category}",
                summary=str(candidate.get("normalized_note", "")),
                review_focus=[
                    "route_note_interpretation",
                    "ln_warning_candidate",
                    "accept_ignore_or_field_verify",
                ],
                evidence_summary={
                    "note_category": category,
                    "potential_ln_signal": candidate.get("potential_ln_signal"),
                    "requires_human_review": candidate.get("requires_human_review"),
                    "scout_interpretation": candidate.get("scout_interpretation"),
                    "source_waypoint_index": candidate.get("source_waypoint_index"),
                    "lat": candidate.get("lat"),
                    "lon": candidate.get("lon"),
                },
            )
        )
    return items


def _runtime_handoff_items(
    fixture_root: Path,
    project: dict[str, Any],
) -> list[ReviewQueueItem]:
    ref_key = "runtime_handoff_metadata_ref"
    ref = _required_project_ref(project, ref_key)
    payload = _load_json(fixture_root / ref)
    boundary = payload.get("boundary", {})
    if boundary.get("candidate_metadata_only") is not True:
        return []
    return [
        ReviewQueueItem(
            item_id=f"review_queue.{project['project_id']}.runtime_handoff.{payload.get('manifest_id', 'candidate_metadata')}",
            category=ReviewQueueCategory.RUNTIME_HANDOFF,
            source_ref_key=ref_key,
            source_ref=ref,
            source_artifact_kind=payload.get("artifact_kind", "pretrip_runtime_handoff_metadata"),
            candidate_ref=str(payload.get("manifest_id", ref)),
            severity="review",
            title="Runtime handoff metadata gate",
            summary="Candidate handoff metadata needs human review before any later runtime integration.",
            review_focus=[
                "readiness_refs",
                "route_refs",
                "reviewed_mission_graph_ref",
                "runtime_boundary",
            ],
            evidence_summary={
                "status": payload.get("status"),
                "plan_version_id": payload.get("plan_version_id"),
                "runtime_write_count": payload.get("counts", {}).get("runtime_write_count"),
                "safety_call_count": payload.get("counts", {}).get("safety_call_count"),
                "bridge_mutation_count": payload.get("counts", {}).get("bridge_mutation_count"),
                "phase1_runtime_mutation_allowed": boundary.get("phase1_runtime_mutation_allowed"),
            },
        )
    ]


def _departure_bundle_items(
    fixture_root: Path,
    project: dict[str, Any],
) -> list[ReviewQueueItem]:
    ref_key = "departure_bundle_manifest_ref"
    ref = _required_project_ref(project, ref_key)
    payload = _load_json(fixture_root / ref)
    boundary = payload.get("boundary", {})
    if boundary.get("human_review_required_before_departure") is not True:
        return []
    return [
        ReviewQueueItem(
            item_id=f"review_queue.{project['project_id']}.departure_bundle.{payload.get('bundle_id', 'candidate_bundle')}",
            category=ReviewQueueCategory.DEPARTURE_BUNDLE,
            source_ref_key=ref_key,
            source_ref=ref,
            source_artifact_kind=payload.get("artifact_kind", "pretrip_departure_bundle_manifest"),
            candidate_ref=str(payload.get("bundle_id", ref)),
            severity="review",
            title="Departure bundle human-review gate",
            summary="Frozen candidate departure bundle is not real departure approval.",
            review_focus=[
                "readiness_refs",
                "resource_plan",
                "remote_summary",
                "terrain_refs",
                "audit_refs",
            ],
            evidence_summary={
                "status": payload.get("status"),
                "required_ref_count": payload.get("counts", {}).get("required_ref_count"),
                "not_departure_approval": boundary.get("not_departure_approval"),
                "phase1_runtime_mutation_allowed": boundary.get("phase1_runtime_mutation_allowed"),
                "phase2_writeback_allowed": boundary.get("phase2_writeback_allowed"),
            },
        )
    ]


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
        raise ValueError(f"project.json missing required review queue ref: {ref_key}")
    return str(ref)


def _ordered_existing_refs(project: dict[str, Any], ref_keys: list[str]) -> list[str]:
    return [str(project[key]) for key in ref_keys if project.get(key)]


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _assert_no_raw_or_runtime_fragments(payload: dict[str, Any]) -> None:
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
        "tel:",
        "phone:",
        "email:",
        "+886",
    ]
    for fragment in forbidden_fragments:
        if fragment in serialized:
            raise ValueError(f"review queue contains forbidden raw/runtime fragment: {fragment}")
