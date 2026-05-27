from __future__ import annotations

import json
import os
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from spatial_imprint_models import (
    SpatialImprint,
    SpatialImprintBoundary,
    SpatialImprintPlantingSource,
    SpatialImprintSet,
)


DEFAULT_SPATIAL_IMPRINT_CANDIDATES_REF = "candidates/spatial_imprints.json"
DEFAULT_SPATIAL_IMPRINT_REVIEWS_REF = "reviews/spatial_imprint_reviews.json"
DEFAULT_SPATIAL_IMPRINT_SET_REF = "outputs/spatial_imprint_set.json"
DEFAULT_SPATIAL_IMPRINT_MANIFEST_REF = "outputs/spatial_imprint_manifest.json"


SpatialImprintReviewDecision = Literal["accepted", "corrected", "rejected", "disabled"]


class StrictPreTripSpatialImprintModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PreTripSpatialImprintCandidateBoundary(StrictPreTripSpatialImprintModel):
    candidate_only: Literal[True] = True
    requires_human_review_before_package_use: Literal[True] = True
    reviewed_imprint_set: Literal[False] = False
    runtime_safety_truth: Literal[False] = False
    phase1_runtime_mutation_allowed: Literal[False] = False
    safety_api_calls_allowed: Literal[False] = False
    remote_outbound_send_allowed: Literal[False] = False
    hardware_control_allowed: Literal[False] = False


class PreTripSpatialImprintCandidateSet(StrictPreTripSpatialImprintModel):
    artifact_kind: Literal["pretrip_spatial_imprint_candidates"] = (
        "pretrip_spatial_imprint_candidates"
    )
    schema_version: str = "0.1.0"
    project_id: str = Field(min_length=1)
    candidates: list[SpatialImprint] = Field(default_factory=list)
    boundary: PreTripSpatialImprintCandidateBoundary = Field(
        default_factory=PreTripSpatialImprintCandidateBoundary
    )
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_candidate_boundary(self) -> "PreTripSpatialImprintCandidateSet":
        _assert_no_forbidden_fragments(self.model_dump(mode="json"))
        return self


class PreTripSpatialImprintReviewBoundary(StrictPreTripSpatialImprintModel):
    append_only_review_log: Literal[True] = True
    candidate_review_only: Literal[True] = True
    creates_runtime_truth: Literal[False] = False
    phase1_runtime_mutation_allowed: Literal[False] = False
    safety_api_calls_allowed: Literal[False] = False
    remote_outbound_send_allowed: Literal[False] = False
    hardware_control_allowed: Literal[False] = False


class PreTripSpatialImprintReviewRecord(StrictPreTripSpatialImprintModel):
    review_id: str = Field(min_length=1)
    candidate_ref: str = Field(min_length=1)
    decision: SpatialImprintReviewDecision
    reviewed_by: str = Field(min_length=1)
    reviewed_at: str
    summary: str = Field(min_length=1)
    corrected_imprint: SpatialImprint | None = None
    source_refs: list[str] = Field(default_factory=list)

    @field_validator("reviewed_at")
    @classmethod
    def validate_reviewed_at(cls, value: str) -> str:
        from spatial_imprint_models import parse_spatial_datetime

        parse_spatial_datetime(value)
        return value

    @model_validator(mode="after")
    def enforce_review_shape(self) -> "PreTripSpatialImprintReviewRecord":
        if self.decision == "corrected" and self.corrected_imprint is None:
            raise ValueError("corrected spatial imprint review requires corrected_imprint")
        if self.decision != "corrected" and self.corrected_imprint is not None:
            raise ValueError("corrected_imprint is only allowed for corrected decisions")
        _assert_no_forbidden_fragments(self.model_dump(mode="json"))
        return self


class PreTripSpatialImprintReviewLog(StrictPreTripSpatialImprintModel):
    artifact_kind: Literal["pretrip_spatial_imprint_review_log"] = (
        "pretrip_spatial_imprint_review_log"
    )
    schema_version: str = "0.1.0"
    project_id: str = Field(min_length=1)
    records: list[PreTripSpatialImprintReviewRecord] = Field(default_factory=list)
    boundary: PreTripSpatialImprintReviewBoundary = Field(
        default_factory=PreTripSpatialImprintReviewBoundary
    )
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_review_log_boundary(self) -> "PreTripSpatialImprintReviewLog":
        seen: set[str] = set()
        for record in self.records:
            if record.candidate_ref in seen:
                raise ValueError(f"duplicate spatial imprint review: {record.candidate_ref}")
            seen.add(record.candidate_ref)
        _assert_no_forbidden_fragments(self.model_dump(mode="json"))
        return self


class PreTripSpatialImprintExportCounts(StrictPreTripSpatialImprintModel):
    candidate_count: int = Field(ge=0)
    review_record_count: int = Field(ge=0)
    reviewed_imprint_count: int = Field(ge=0)
    accepted_count: int = Field(ge=0)
    corrected_count: int = Field(ge=0)
    rejected_count: int = Field(ge=0)
    disabled_count: int = Field(ge=0)
    runtime_truth_count: Literal[0] = 0
    phase1_runtime_mutation_count: Literal[0] = 0
    safety_api_call_count: Literal[0] = 0
    remote_outbound_send_count: Literal[0] = 0
    hardware_control_count: Literal[0] = 0


class PreTripSpatialImprintExportBoundary(StrictPreTripSpatialImprintModel):
    reviewed_pretrip_addendum: Literal[True] = True
    package_addendum_candidate: Literal[True] = True
    runtime_safety_truth: Literal[False] = False
    compiles_mission_graph: Literal[False] = False
    final_mission_graph_mutation_allowed: Literal[False] = False
    runtime_activation_allowed: Literal[False] = False
    phase1_runtime_mutation_allowed: Literal[False] = False
    safety_api_calls_allowed: Literal[False] = False
    phase2_writeback_allowed: Literal[False] = False
    remote_outbound_send_allowed: Literal[False] = False
    hardware_control_allowed: Literal[False] = False
    notes: list[str] = Field(
        default_factory=lambda: [
            "Spatial Imprint export / 空間印記匯出 is a reviewed pretrip addendum.",
            "Trigger evaluation remains deterministic and advisory.",
            "This exporter does not activate runtime, call safety APIs, or control hardware.",
        ]
    )


class PreTripSpatialImprintExportManifest(StrictPreTripSpatialImprintModel):
    artifact_kind: Literal["pretrip_spatial_imprint_export_manifest"] = (
        "pretrip_spatial_imprint_export_manifest"
    )
    schema_version: str = "0.1.0"
    project_id: str = Field(min_length=1)
    candidates_ref: str
    reviews_ref: str
    spatial_imprint_set_ref: str
    counts: PreTripSpatialImprintExportCounts
    reviewed_imprint_ids: list[str] = Field(default_factory=list)
    rejected_audit_refs: list[str] = Field(default_factory=list)
    disabled_audit_refs: list[str] = Field(default_factory=list)
    boundary: PreTripSpatialImprintExportBoundary = Field(
        default_factory=PreTripSpatialImprintExportBoundary
    )
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_export_boundary(self) -> "PreTripSpatialImprintExportManifest":
        if self.counts.runtime_truth_count != 0:
            raise ValueError("spatial imprint export must not create runtime truth")
        _assert_no_forbidden_fragments(self.model_dump(mode="json"))
        return self

    def to_json(self) -> str:
        return _json_text(self.model_dump(mode="json"))


def build_pretrip_spatial_imprint_export(
    *,
    project_id: str,
    candidates_ref: str,
    candidate_set: PreTripSpatialImprintCandidateSet | dict[str, Any],
    reviews_ref: str,
    review_log: PreTripSpatialImprintReviewLog | dict[str, Any],
    spatial_imprint_set_ref: str = DEFAULT_SPATIAL_IMPRINT_SET_REF,
) -> tuple[SpatialImprintSet, PreTripSpatialImprintExportManifest]:
    candidates = PreTripSpatialImprintCandidateSet.model_validate(candidate_set)
    reviews = PreTripSpatialImprintReviewLog.model_validate(review_log)
    if candidates.project_id != project_id:
        raise ValueError("spatial imprint candidate project_id does not match workspace")
    if reviews.project_id != project_id:
        raise ValueError("spatial imprint review project_id does not match workspace")

    candidate_by_id = {candidate.imprint_id: candidate for candidate in candidates.candidates}
    if len(candidate_by_id) != len(candidates.candidates):
        raise ValueError("duplicate spatial imprint candidate id")

    reviewed_imprints: list[SpatialImprint] = []
    rejected_refs: list[str] = []
    disabled_refs: list[str] = []
    decision_counts = Counter(record.decision for record in reviews.records)

    for record in reviews.records:
        candidate = candidate_by_id.get(record.candidate_ref)
        if candidate is None:
            raise ValueError(f"unknown spatial imprint candidate_ref: {record.candidate_ref}")
        if record.decision == "accepted":
            reviewed_imprints.append(
                _as_reviewed_imprint(
                    candidate,
                    record=record,
                    decision_source_ref=reviews_ref,
                )
            )
        elif record.decision == "corrected":
            corrected = record.corrected_imprint
            if corrected is None:
                raise ValueError("corrected review missing corrected_imprint")
            reviewed_imprints.append(
                _as_reviewed_imprint(
                    corrected,
                    record=record,
                    decision_source_ref=reviews_ref,
                )
            )
        elif record.decision == "rejected":
            rejected_refs.append(record.candidate_ref)
        elif record.decision == "disabled":
            disabled_refs.append(record.candidate_ref)

    imprint_set = SpatialImprintSet(trip_id=project_id, imprints=reviewed_imprints)
    manifest = PreTripSpatialImprintExportManifest(
        project_id=project_id,
        candidates_ref=candidates_ref,
        reviews_ref=reviews_ref,
        spatial_imprint_set_ref=spatial_imprint_set_ref,
        counts=PreTripSpatialImprintExportCounts(
            candidate_count=len(candidates.candidates),
            review_record_count=len(reviews.records),
            reviewed_imprint_count=len(reviewed_imprints),
            accepted_count=decision_counts["accepted"],
            corrected_count=decision_counts["corrected"],
            rejected_count=decision_counts["rejected"],
            disabled_count=decision_counts["disabled"],
        ),
        reviewed_imprint_ids=[imprint.imprint_id for imprint in reviewed_imprints],
        rejected_audit_refs=rejected_refs,
        disabled_audit_refs=disabled_refs,
        notes=[
            "Reviewed spatial imprints remain advisory cues and are not Phase 1 safety truth.",
            "Runtime loading must still pass the departure/runtime handoff chain.",
        ],
    )
    return imprint_set, manifest


def write_pretrip_spatial_imprint_export_for_workspace(
    project_root: Path | str,
) -> PreTripSpatialImprintExportManifest:
    workspace_root, imprint_set, manifest, set_ref, manifest_ref = (
        build_pretrip_spatial_imprint_export_for_workspace(project_root)
    )
    _replace_json(
        workspace_root / set_ref,
        _json_text(imprint_set.model_dump(mode="json")),
    )
    _replace_json(workspace_root / manifest_ref, manifest.to_json())
    return manifest


def build_pretrip_spatial_imprint_export_for_workspace(
    project_root: Path | str,
) -> tuple[Path, SpatialImprintSet, PreTripSpatialImprintExportManifest, str, str]:
    root = Path(project_root)
    project_path = root if root.name == "project.json" else root / "project.json"
    _require_file(project_path, "project.json")
    workspace_root = project_path.parent
    project = _load_json(project_path)
    project_id = _require_project_ref(project, "project_id")
    candidates_ref = _project_ref(
        project,
        "spatial_imprint_candidates_ref",
        DEFAULT_SPATIAL_IMPRINT_CANDIDATES_REF,
    )
    reviews_ref = _project_ref(
        project,
        "spatial_imprint_reviews_ref",
        DEFAULT_SPATIAL_IMPRINT_REVIEWS_REF,
    )
    set_ref = _project_ref(
        project,
        "spatial_imprint_set_ref",
        DEFAULT_SPATIAL_IMPRINT_SET_REF,
    )
    manifest_ref = _project_ref(
        project,
        "spatial_imprint_manifest_ref",
        DEFAULT_SPATIAL_IMPRINT_MANIFEST_REF,
    )

    candidates_path = workspace_root / candidates_ref
    reviews_path = workspace_root / reviews_ref
    set_path = workspace_root / set_ref
    manifest_path = workspace_root / manifest_ref
    _require_file(candidates_path, "spatial_imprint_candidates_ref")
    _require_file(reviews_path, "spatial_imprint_reviews_ref")
    for destination, label in (
        (set_path, "spatial_imprint_set_ref"),
        (manifest_path, "spatial_imprint_manifest_ref"),
    ):
        _require_workspace_relative_path(destination, workspace_root, label)

    imprint_set, manifest = build_pretrip_spatial_imprint_export(
        project_id=project_id,
        candidates_ref=candidates_ref,
        candidate_set=_load_json(candidates_path),
        reviews_ref=reviews_ref,
        review_log=_load_json(reviews_path),
        spatial_imprint_set_ref=set_ref,
    )
    return workspace_root, imprint_set, manifest, set_ref, manifest_ref


def load_pretrip_spatial_imprint_export_manifest(
    path: Path | str,
) -> PreTripSpatialImprintExportManifest:
    return PreTripSpatialImprintExportManifest.model_validate_json(
        Path(path).read_text(encoding="utf-8")
    )


def _as_reviewed_imprint(
    imprint: SpatialImprint,
    *,
    record: PreTripSpatialImprintReviewRecord,
    decision_source_ref: str,
) -> SpatialImprint:
    source_refs = [
        *imprint.source_refs,
        {
            "source_id": record.review_id,
            "source_path": decision_source_ref,
            "evidence_type": "pretrip_spatial_imprint_review",
        },
    ]
    return SpatialImprint.model_validate(
        {
            **imprint.model_dump(mode="json"),
            "planting_source": SpatialImprintPlantingSource.PRETRIP_REVIEWED.value,
            "source_refs": source_refs,
            "boundary": SpatialImprintBoundary().model_dump(mode="json"),
        }
    )


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _require_project_ref(project: dict[str, Any], key: str) -> str:
    value = project.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"project.json missing required string field: {key}")
    _reject_absolute_or_parent_ref(value, key)
    return value


def _project_ref(project: dict[str, Any], key: str, default: str) -> str:
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


def _json_text(payload: Any) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"


def _assert_no_forbidden_fragments(payload: Any) -> None:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    forbidden = (
        "/safety/",
        "Phase1IncidentBridge",
        "ObservedFact",
        "Final MissionGraph",
        "MissionGraph(",
        "raw_gpx",
        "raw_payload",
    )
    for fragment in forbidden:
        if fragment in text:
            raise ValueError(f"forbidden spatial imprint export fragment: {fragment}")
