from __future__ import annotations

import json
import os
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from pretrip_route_note_review_options import (
    ALLOWED_ADMIN_DISPOSITIONS,
    AdminDisposition,
    RouteNoteReviewOption,
    load_route_note_review_options,
)


DEFAULT_ROUTE_NOTE_DISPOSITION_LOG_REF = "reviews/route_note_disposition_log.json"

FORBIDDEN_RAW_PAYLOAD_FRAGMENTS = (
    "<gpx",
    "<trk",
    "<trkpt",
    "<wpt",
    "raw_gpx",
    "raw_payload",
    "raw_samples",
    ".gpx",
    ".fit",
    ".tcx",
    "PdrSample",
    "catographydata",
    "MissionGraph(",
    "Phase1IncidentBridge",
    "/safety/",
)


class RouteNoteDispositionModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RouteNoteDispositionRecord(RouteNoteDispositionModel):
    disposition_id: str
    candidate_ref: str
    selected_ref: str
    selected_disposition: AdminDisposition
    source_review_options_ref: str
    source_review_options_artifact_id: str
    source_review_option_id: str
    source_proposal_id: str
    source_route_note_candidate_id: str
    source_waypoint_index: int = Field(ge=0)
    source_note_category: Literal["hazard_hint", "route_condition_hint"]
    proposal_kind: Literal["warning_coverage", "hint_coverage"]
    proposed_coverage_label: str
    reviewer_alias: str
    decided_at: str
    append_only: Literal[True] = True
    metadata_only: Literal[True] = True
    source_mutation_allowed: Literal[False] = False
    package_mutation_allowed: Literal[False] = False
    mission_graph_mutation_allowed: Literal[False] = False
    runtime_mutation_allowed: Literal[False] = False
    phase1_runtime_mutation_allowed: Literal[False] = False
    phase2_writeback_allowed: Literal[False] = False
    raw_gpx_embedded: Literal[False] = False

    @field_validator("decided_at")
    @classmethod
    def require_iso_decided_at(cls, value: str) -> str:
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("decided_at must be an ISO-8601 datetime") from exc
        return value

    @model_validator(mode="after")
    def enforce_metadata_boundary(self) -> "RouteNoteDispositionRecord":
        if self.candidate_ref != self.source_route_note_candidate_id:
            raise ValueError("candidate_ref must match source_route_note_candidate_id")
        _assert_no_raw_payload_fragments(self.model_dump(mode="json"))
        return self


class RouteNoteDispositionCounts(RouteNoteDispositionModel):
    disposition_count: int = Field(ge=0)
    promote_hint_count: int = Field(ge=0)
    promote_warning_count: int = Field(ge=0)
    ignore_count: int = Field(ge=0)
    field_verify_count: int = Field(ge=0)
    source_mutation_count: Literal[0] = 0
    package_mutation_count: Literal[0] = 0
    mission_graph_mutation_count: Literal[0] = 0
    runtime_mutation_count: Literal[0] = 0
    phase1_runtime_mutation_count: Literal[0] = 0
    phase2_writeback_count: Literal[0] = 0
    raw_gpx_payload_count: Literal[0] = 0


class RouteNoteDispositionBoundary(RouteNoteDispositionModel):
    append_only: Literal[True] = True
    local_workspace_only: Literal[True] = True
    metadata_only: Literal[True] = True
    source_mutation_allowed: Literal[False] = False
    package_mutation_allowed: Literal[False] = False
    mission_graph_mutation_allowed: Literal[False] = False
    runtime_mutation_allowed: Literal[False] = False
    phase1_runtime_mutation_allowed: Literal[False] = False
    phase2_writeback_allowed: Literal[False] = False
    raw_gpx_embedded: Literal[False] = False
    notes: tuple[str, ...] = Field(default_factory=tuple)


class RouteNoteDispositionLog(RouteNoteDispositionModel):
    log_id: str
    artifact_kind: Literal["pretrip_route_note_disposition_log"] = (
        "pretrip_route_note_disposition_log"
    )
    project_id: str
    source_review_options_ref: str
    allowed_dispositions: tuple[AdminDisposition, ...] = ALLOWED_ADMIN_DISPOSITIONS
    records: tuple[RouteNoteDispositionRecord, ...] = Field(default_factory=tuple)
    counts: RouteNoteDispositionCounts
    boundary: RouteNoteDispositionBoundary = Field(
        default_factory=RouteNoteDispositionBoundary
    )
    notes: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def enforce_log_boundary(self) -> "RouteNoteDispositionLog":
        if self.allowed_dispositions != ALLOWED_ADMIN_DISPOSITIONS:
            raise ValueError("allowed_dispositions must match route-note admin dispositions")
        _reject_duplicate_disposition_ids(self.records)
        _reject_duplicate_candidate_refs(self.records)
        _assert_no_raw_payload_fragments(self.model_dump(mode="json"))
        return self

    def to_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n"


def append_route_note_disposition(
    workspace_root: Path | str,
    *,
    route_note_ref: str,
    disposition: AdminDisposition,
    reviewer_alias: str,
    decided_at: str,
) -> RouteNoteDispositionLog:
    if disposition not in ALLOWED_ADMIN_DISPOSITIONS:
        raise ValueError(f"unsupported route-note disposition: {disposition}")
    root = _require_workspace_root(workspace_root)
    project = _load_project(root)
    project_id = _require_project_string(project, "project_id")
    review_options_ref = _require_project_relative_ref(
        project, "route_note_review_options_ref"
    )
    review_options_path = root / review_options_ref
    if not review_options_path.is_file():
        raise FileNotFoundError(
            f"missing route_note_review_options_ref: {review_options_path}"
        )

    options = load_route_note_review_options(review_options_path)
    selected_option = _find_review_option(options.options, route_note_ref)
    log_path = root / DEFAULT_ROUTE_NOTE_DISPOSITION_LOG_REF
    _require_workspace_relative_path(log_path, root, "route_note_disposition_log")
    log = _load_or_create_log(
        log_path,
        project_id=project_id,
        source_review_options_ref=review_options_ref,
    )
    record = build_route_note_disposition_record(
        selected_option,
        route_note_ref=route_note_ref,
        disposition=disposition,
        reviewer_alias=reviewer_alias,
        decided_at=decided_at,
        project_id=project_id,
        source_review_options_ref=review_options_ref,
        source_review_options_artifact_id=options.artifact_id,
    )
    rebuilt = rebuild_route_note_disposition_log(log, [*log.records, record])
    _replace_json(log_path, rebuilt.to_json())
    return rebuilt


def build_route_note_disposition_record(
    option: RouteNoteReviewOption,
    *,
    route_note_ref: str,
    disposition: AdminDisposition,
    reviewer_alias: str,
    decided_at: str,
    project_id: str,
    source_review_options_ref: str,
    source_review_options_artifact_id: str,
) -> RouteNoteDispositionRecord:
    if disposition not in ALLOWED_ADMIN_DISPOSITIONS:
        raise ValueError(f"unsupported route-note disposition: {disposition}")
    candidate_ref = option.source_route_note_candidate_id
    return RouteNoteDispositionRecord(
        disposition_id=f"route_note_disposition.{project_id}.{_ref_slug(candidate_ref)}",
        candidate_ref=candidate_ref,
        selected_ref=route_note_ref,
        selected_disposition=disposition,
        source_review_options_ref=source_review_options_ref,
        source_review_options_artifact_id=source_review_options_artifact_id,
        source_review_option_id=option.option_id,
        source_proposal_id=option.source_proposal_id,
        source_route_note_candidate_id=option.source_route_note_candidate_id,
        source_waypoint_index=option.source_waypoint_index,
        source_note_category=option.source_note_category,
        proposal_kind=option.proposal_kind,
        proposed_coverage_label=option.proposed_coverage_label,
        reviewer_alias=reviewer_alias,
        decided_at=decided_at,
    )


def rebuild_route_note_disposition_log(
    log: RouteNoteDispositionLog,
    records: list[RouteNoteDispositionRecord] | tuple[RouteNoteDispositionRecord, ...],
) -> RouteNoteDispositionLog:
    rebuilt_records = tuple(records)
    _reject_duplicate_candidate_refs(rebuilt_records)
    _reject_duplicate_disposition_ids(rebuilt_records)
    counts = Counter(record.selected_disposition for record in rebuilt_records)
    return RouteNoteDispositionLog(
        log_id=log.log_id,
        project_id=log.project_id,
        source_review_options_ref=log.source_review_options_ref,
        records=rebuilt_records,
        counts=RouteNoteDispositionCounts(
            disposition_count=len(rebuilt_records),
            promote_hint_count=counts["promote_hint"],
            promote_warning_count=counts["promote_warning"],
            ignore_count=counts["ignore"],
            field_verify_count=counts["field_verify"],
        ),
        boundary=log.boundary,
        notes=log.notes,
    )


def load_route_note_disposition_log(path: Path | str) -> RouteNoteDispositionLog:
    return RouteNoteDispositionLog.model_validate_json(
        Path(path).read_text(encoding="utf-8")
    )


def _load_or_create_log(
    path: Path,
    *,
    project_id: str,
    source_review_options_ref: str,
) -> RouteNoteDispositionLog:
    if path.exists():
        log = load_route_note_disposition_log(path)
        if log.project_id != project_id:
            raise ValueError("route-note disposition log project_id does not match workspace")
        if log.source_review_options_ref != source_review_options_ref:
            raise ValueError(
                "route-note disposition log source_review_options_ref does not match workspace"
            )
        return log
    return RouteNoteDispositionLog(
        log_id=f"route_note_disposition_log.{project_id}.v0",
        project_id=project_id,
        source_review_options_ref=source_review_options_ref,
        counts=RouteNoteDispositionCounts(
            disposition_count=0,
            promote_hint_count=0,
            promote_warning_count=0,
            ignore_count=0,
            field_verify_count=0,
        ),
        boundary=RouteNoteDispositionBoundary(
            notes=(
                "This append-only log records route-note disposition drafts in a copied local workspace only.",
                "Records are metadata pointers to route-note review options; source artifacts and runtime outputs are not mutated.",
            ),
        ),
        notes=(
            "Parent integration can wire this log into admin UI and later review-decision flows.",
        ),
    )


def _find_review_option(
    options: tuple[RouteNoteReviewOption, ...],
    route_note_ref: str,
) -> RouteNoteReviewOption:
    matches = [
        option
        for option in options
        if route_note_ref
        in {
            option.option_id,
            option.source_proposal_id,
            option.source_route_note_candidate_id,
        }
    ]
    if not matches:
        raise ValueError(f"route-note option/proposal/candidate ref not found: {route_note_ref}")
    if len(matches) > 1:
        raise ValueError(f"route-note ref is ambiguous: {route_note_ref}")
    return matches[0]


def _load_project(workspace_root: Path) -> dict[str, Any]:
    project_path = workspace_root / "project.json"
    if not project_path.is_file():
        raise FileNotFoundError(f"missing workspace project.json: {project_path}")
    payload = json.loads(project_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("project.json must contain a JSON object")
    return payload


def _require_workspace_root(workspace_root: Path | str) -> Path:
    root = Path(workspace_root)
    if not root.is_dir():
        raise FileNotFoundError(f"workspace root does not exist: {root}")
    if root.name == "project.json":
        raise ValueError("workspace root must be a directory, not project.json")
    resolved = root.resolve()
    fixture_root = (Path(__file__).resolve().parent / "tests" / "fixtures").resolve()
    try:
        resolved.relative_to(fixture_root)
    except ValueError:
        return root
    raise ValueError("route-note dispositions must be written to a copied workspace, not repo fixtures")


def _require_project_string(project: dict[str, Any], key: str) -> str:
    value = project.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"project.json missing required string field: {key}")
    return value


def _require_project_relative_ref(project: dict[str, Any], key: str) -> str:
    value = _require_project_string(project, key)
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{key} must be a project-relative path")
    return value


def _require_workspace_relative_path(path: Path, workspace_root: Path, label: str) -> None:
    try:
        path.resolve().relative_to(workspace_root.resolve())
    except ValueError as exc:
        raise ValueError(f"{label} must resolve inside the project workspace") from exc


def _reject_duplicate_disposition_ids(
    records: tuple[RouteNoteDispositionRecord, ...],
) -> None:
    seen: set[str] = set()
    for record in records:
        if record.disposition_id in seen:
            raise ValueError(f"duplicate route-note disposition_id: {record.disposition_id}")
        seen.add(record.disposition_id)


def _reject_duplicate_candidate_refs(
    records: tuple[RouteNoteDispositionRecord, ...],
) -> None:
    seen: set[str] = set()
    for record in records:
        if record.candidate_ref in seen:
            raise ValueError(f"duplicate route-note candidate_ref: {record.candidate_ref}")
        seen.add(record.candidate_ref)


def _assert_no_raw_payload_fragments(value: object) -> None:
    if isinstance(value, dict):
        for item in value.values():
            _assert_no_raw_payload_fragments(item)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _assert_no_raw_payload_fragments(item)
        return
    if isinstance(value, str):
        _reject_raw_payload_fragment(value)


def _reject_raw_payload_fragment(value: str) -> None:
    lowered = value.lower()
    for fragment in FORBIDDEN_RAW_PAYLOAD_FRAGMENTS:
        if fragment.lower() in lowered:
            raise ValueError(f"forbidden raw payload fragment: {fragment}")


def _ref_slug(value: str) -> str:
    return "".join(character if character.isalnum() else "_" for character in value)


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
