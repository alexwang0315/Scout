from __future__ import annotations

import json
import os
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


WORKSPACE_EDIT_RULE_VERSION = "pretrip_workspace_edit.v2"
DEFAULT_WORKSPACE_EDIT_LOG_REF = "reviews/workspace_edit_log.json"
REPO_FIXTURE_ROOT = Path(__file__).resolve().parent / "tests" / "fixtures"

WorkspaceEditOperation = Literal[
    "add_checkpoint",
    "add_waypoint",
    "remove_checkpoint",
    "remove_waypoint",
    "add_retreat_route",
    "remove_retreat_route",
    "feature_edit",
    "select_trail_generate_waypoint",
    "rectangle_group_selection",
]

WorkspaceEditTargetKind = Literal[
    "checkpoint_waypoint",
    "retreat_route",
    "feature",
    "trail_selection",
    "rectangle_selection",
]

ADD_CHECKPOINT_OPERATIONS = frozenset(
    {"add_checkpoint", "add_waypoint", "select_trail_generate_waypoint"}
)
REMOVE_CHECKPOINT_OPERATIONS = frozenset({"remove_checkpoint", "remove_waypoint"})
ADD_RETREAT_ROUTE_OPERATIONS = frozenset({"add_retreat_route"})
REMOVE_RETREAT_ROUTE_OPERATIONS = frozenset({"remove_retreat_route"})

FORBIDDEN_PAYLOAD_FRAGMENTS = (
    "<gpx",
    "<trk",
    "<trkpt",
    "<wpt",
    "raw_gpx",
    "raw_payload",
    "raw_samples",
    "Final MissionGraph",
    "MissionGraph(",
    "Phase1IncidentBridge",
    "/safety/",
    "PdrSample",
    "catographydata",
)
FORBIDDEN_TRUE_KEYS = frozenset(
    {
        "source_mutation_allowed",
        "candidate_artifact_mutation_allowed",
        "package_mutation_allowed",
        "mission_graph_mutation_allowed",
        "runtime_mutation_allowed",
        "phase1_runtime_mutation_allowed",
        "phase2_writeback_allowed",
        "compiles_mission_graph",
        "final_mission_graph_compiled",
        "external_api_calls_made",
        "raw_payloads_embedded",
    }
)


class WorkspaceEditModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class PreTripWorkspaceEditRequest(WorkspaceEditModel):
    operation: WorkspaceEditOperation
    summary: str = Field(min_length=1)
    reviewer_alias: str = Field(default="trip_leader", min_length=1)
    created_at: str | None = Field(
        default=None,
        validation_alias=AliasChoices("created_at", "decided_at"),
    )
    target_ref: str | None = Field(
        default=None,
        min_length=1,
        validation_alias=AliasChoices("target_ref", "candidate_ref", "feature_ref"),
    )
    target_refs: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    candidate_payload: dict[str, Any] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("candidate_payload", "candidate"),
    )
    field_updates: dict[str, Any] = Field(default_factory=dict)
    selection_payload: dict[str, Any] = Field(
        default_factory=dict,
        validation_alias=AliasChoices(
            "selection_payload",
            "selection",
            "selection_geometry",
        ),
    )
    persist_to_workspace: bool = True

    @field_validator("created_at")
    @classmethod
    def require_iso_created_at(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("created_at must be an ISO-8601 datetime") from exc
        return value

    @model_validator(mode="after")
    def enforce_operation_shape(self) -> "PreTripWorkspaceEditRequest":
        self.summary = self.summary.strip()
        if not self.summary:
            raise ValueError("summary must not be blank")

        if self.operation in ADD_CHECKPOINT_OPERATIONS and not self.candidate_payload:
            raise ValueError(f"{self.operation} requires candidate_payload")
        if self.operation in ADD_RETREAT_ROUTE_OPERATIONS and not self.candidate_payload:
            raise ValueError("add_retreat_route requires candidate_payload")
        if self.operation in (
            REMOVE_CHECKPOINT_OPERATIONS | REMOVE_RETREAT_ROUTE_OPERATIONS
        ) and not self.selected_target_refs:
            raise ValueError(f"{self.operation} requires target_ref or target_refs")
        if self.operation == "feature_edit":
            if not self.target_ref:
                raise ValueError("feature_edit requires target_ref")
            if not self.field_updates:
                raise ValueError("feature_edit requires field_updates")
        if (
            self.operation == "rectangle_group_selection"
            and not self.target_refs
            and not self.selection_payload
        ):
            raise ValueError(
                "rectangle_group_selection requires target_refs or selection_payload"
            )

        _assert_candidate_only_payload(self.model_dump(mode="json"))
        return self

    @property
    def selected_target_refs(self) -> list[str]:
        refs = []
        if self.target_ref:
            refs.append(self.target_ref)
        refs.extend(self.target_refs)
        return refs


class PreTripWorkspaceEditRecord(WorkspaceEditModel):
    edit_id: str
    operation: WorkspaceEditOperation
    target_kind: WorkspaceEditTargetKind
    target_ref: str | None = None
    target_refs: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    reviewer_alias: str
    created_at: str
    summary: str
    candidate_payload: dict[str, Any] = Field(default_factory=dict)
    field_updates: dict[str, Any] = Field(default_factory=dict)
    selection_payload: dict[str, Any] = Field(default_factory=dict)
    append_only: Literal[True] = True
    candidate_only: Literal[True] = True
    local_workspace_only: Literal[True] = True
    source_mutation_allowed: Literal[False] = False
    candidate_artifact_mutation_allowed: Literal[False] = False
    package_mutation_allowed: Literal[False] = False
    mission_graph_mutation_allowed: Literal[False] = False
    runtime_mutation_allowed: Literal[False] = False
    phase1_runtime_mutation_allowed: Literal[False] = False
    phase2_writeback_allowed: Literal[False] = False
    compiles_mission_graph: Literal[False] = False
    final_mission_graph_compiled: Literal[False] = False
    external_api_calls_made: Literal[False] = False
    raw_payloads_embedded: Literal[False] = False

    @field_validator("created_at")
    @classmethod
    def require_record_iso_created_at(cls, value: str) -> str:
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("created_at must be an ISO-8601 datetime") from exc
        return value

    @model_validator(mode="after")
    def enforce_record_boundary(self) -> "PreTripWorkspaceEditRecord":
        _assert_candidate_only_payload(self.model_dump(mode="json"))
        return self


class PreTripWorkspaceEditCounts(WorkspaceEditModel):
    edit_count: int = Field(ge=0)
    add_checkpoint_count: int = Field(ge=0)
    add_waypoint_count: int = Field(ge=0)
    remove_checkpoint_count: int = Field(ge=0)
    remove_waypoint_count: int = Field(ge=0)
    add_retreat_route_count: int = Field(ge=0)
    remove_retreat_route_count: int = Field(ge=0)
    feature_edit_count: int = Field(ge=0)
    select_trail_generate_waypoint_count: int = Field(ge=0)
    rectangle_group_selection_count: int = Field(ge=0)
    candidate_only_edit_count: int = Field(ge=0)
    source_mutation_count: Literal[0] = 0
    candidate_artifact_mutation_count: Literal[0] = 0
    package_mutation_count: Literal[0] = 0
    mission_graph_mutation_count: Literal[0] = 0
    runtime_mutation_count: Literal[0] = 0
    phase1_runtime_mutation_count: Literal[0] = 0
    phase2_writeback_count: Literal[0] = 0
    external_api_call_count: Literal[0] = 0
    raw_payload_count: Literal[0] = 0


class PreTripWorkspaceEditBoundary(WorkspaceEditModel):
    append_only: Literal[True] = True
    local_workspace_only: Literal[True] = True
    candidate_only: Literal[True] = True
    source_mutation_allowed: Literal[False] = False
    candidate_artifact_mutation_allowed: Literal[False] = False
    workspace_candidate_artifact_mutation_allowed: Literal[True] = True
    package_mutation_allowed: Literal[False] = False
    mission_graph_mutation_allowed: Literal[False] = False
    compiles_mission_graph: Literal[False] = False
    final_mission_graph_compiled: Literal[False] = False
    runtime_mutation_allowed: Literal[False] = False
    phase1_runtime_mutation_allowed: Literal[False] = False
    phase2_writeback_allowed: Literal[False] = False
    external_api_calls_made: Literal[False] = False
    raw_payloads_embedded: Literal[False] = False
    repo_fixture_write_allowed: Literal[False] = False
    notes: list[str] = Field(default_factory=list)


class PreTripWorkspaceEditLog(WorkspaceEditModel):
    log_id: str
    artifact_kind: Literal["pretrip_workspace_edit_log"] = (
        "pretrip_workspace_edit_log"
    )
    project_id: str
    workspace_edit_log_ref: str = DEFAULT_WORKSPACE_EDIT_LOG_REF
    conversion_rule_version: Literal["pretrip_workspace_edit.v2"] = (
        WORKSPACE_EDIT_RULE_VERSION
    )
    source_project_refs: dict[str, str] = Field(default_factory=dict)
    records: list[PreTripWorkspaceEditRecord] = Field(default_factory=list)
    counts: PreTripWorkspaceEditCounts
    boundary: PreTripWorkspaceEditBoundary = Field(
        default_factory=PreTripWorkspaceEditBoundary
    )
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_log_boundary(self) -> "PreTripWorkspaceEditLog":
        _reject_duplicate_edit_ids(self.records)
        if self.counts.edit_count != len(self.records):
            raise ValueError("edit_count must match records")
        if self.counts.candidate_only_edit_count != len(self.records):
            raise ValueError("candidate_only_edit_count must match records")
        _assert_candidate_only_payload(self.model_dump(mode="json"))
        return self

    def to_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n"


def append_pretrip_workspace_edit(
    project_root: Path | str,
    request: PreTripWorkspaceEditRequest | dict[str, Any],
    *,
    created_at: str | None = None,
) -> PreTripWorkspaceEditLog:
    workspace_root = _require_workspace_project_root(project_root)
    project = _load_project(workspace_root)
    project_id = _require_project_string(project, "project_id")
    log_path = _workspace_edit_log_path(workspace_root)
    log = _load_or_create_log(
        log_path,
        project_id=project_id,
        source_project_refs=_source_project_refs(project),
    )
    edit_request = (
        request
        if isinstance(request, PreTripWorkspaceEditRequest)
        else PreTripWorkspaceEditRequest.model_validate(request)
    )
    edit_time = (
        edit_request.created_at
        or created_at
        or datetime.now(timezone.utc).isoformat()
    )
    record = build_pretrip_workspace_edit_record(
        edit_request,
        project_id=project_id,
        edit_index=len(log.records) + 1,
        created_at=edit_time,
    )
    rebuilt = rebuild_pretrip_workspace_edit_log(log, [*log.records, record])
    _replace_json(log_path, rebuilt.to_json())
    return rebuilt


def apply_pretrip_workspace_edit_to_workspace(
    project_root: Path | str,
    request: PreTripWorkspaceEditRequest | dict[str, Any],
) -> dict[str, Any]:
    workspace_root = _require_workspace_project_root(project_root)
    project = _load_project(workspace_root)
    project_id = _require_project_string(project, "project_id")
    edit_request = (
        request
        if isinstance(request, PreTripWorkspaceEditRequest)
        else PreTripWorkspaceEditRequest.model_validate(request)
    )
    before_counts = _workspace_candidate_counts(workspace_root, project)
    candidate_mutation = _apply_workspace_candidate_mutation(
        workspace_root,
        project,
        edit_request,
    )
    _write_project(workspace_root, project)
    log = append_pretrip_workspace_edit(workspace_root, edit_request)
    record = log.records[-1].model_dump(mode="json")
    after_counts = _workspace_candidate_counts(workspace_root, project)
    log_path = _workspace_edit_log_path(workspace_root)
    workspace_candidate_artifacts_mutated = candidate_mutation[
        "workspace_candidate_artifacts_mutated"
    ]

    return {
        "project_id": project_id,
        "artifact_kind": log.artifact_kind,
        "persisted": True,
        "append_only": True,
        "candidate_only": True,
        "operation": edit_request.operation,
        "conversion_rule_version": WORKSPACE_EDIT_RULE_VERSION,
        "counts": {
            **log.counts.model_dump(mode="json"),
            "workspace_checkpoint_candidate_count": after_counts[
                "checkpoint_candidate_count"
            ],
            "workspace_retreat_route_candidate_count": after_counts[
                "retreat_route_candidate_count"
            ],
            "workspace_candidate_artifact_mutation_count": (
                1 if workspace_candidate_artifacts_mutated else 0
            ),
        },
        "workspace_candidate_counts": {
            "before": before_counts,
            "after": after_counts,
        },
        "record": record,
        "candidate": candidate_mutation.get("candidate"),
        "paths": {
            "workspace_project_root": str(workspace_root.resolve()),
            "workspace_edit_log": str(log_path),
            "workspace_checkpoints": str(
                _workspace_ref_path(
                    workspace_root,
                    project,
                    "checkpoint_candidates_ref",
                    "checkpoints",
                )
            ),
            "workspace_retreat_routes": str(
                _workspace_ref_path(
                    workspace_root,
                    project,
                    "retreat_routes_ref",
                    "retreat_routes",
                )
            ),
        },
        "boundary": {
            **log.boundary.model_dump(mode="json"),
            "admin_api_write_performed": True,
            "fixture_file_mutation_allowed": False,
            "workspace_file_mutation_allowed": True,
            "workspace_candidate_artifact_mutation_allowed": True,
            "workspace_project_root": str(workspace_root.resolve()),
            "workspace_edit_log_path": str(log_path),
        },
        "mutation": {
            "source_mutated": False,
            "candidate_artifacts_mutated": False,
            "workspace_candidate_artifacts_mutated": workspace_candidate_artifacts_mutated,
            "checkpoint_candidates_mutated": candidate_mutation[
                "checkpoint_candidates_mutated"
            ],
            "retreat_route_candidates_mutated": candidate_mutation[
                "retreat_route_candidates_mutated"
            ],
            "package_mutated": False,
            "mission_graph_mutated": False,
            "runtime_mutated": False,
            "phase1_runtime_mutated": False,
            "phase2_writeback_performed": False,
            "external_api_calls_made": False,
            "fixture_files_mutated": False,
            "workspace_files_mutated": True,
            "workspace_edit_log_mutated": True,
        },
    }


def apply_pretrip_workspace_edit(
    project_root: Path,
    *,
    project_id: str,
    operation: str,
    payload: dict[str, Any],
    edited_at: str | None = None,
    reviewer_alias: str = "trip_leader",
) -> dict[str, Any]:
    """Compatibility wrapper for earlier callers; it records intent only."""
    mapped_operation = {
        "generate_waypoint_from_feature": "select_trail_generate_waypoint",
        "rectangle_group_select": "rectangle_group_selection",
    }.get(operation, operation)
    request_payload: dict[str, Any] = {
        "operation": mapped_operation,
        "summary": str(payload.get("summary") or f"Workspace edit: {operation}"),
        "reviewer_alias": reviewer_alias,
        "created_at": edited_at,
        "candidate_payload": payload
        if mapped_operation
        in {
            "add_checkpoint",
            "add_waypoint",
            "add_retreat_route",
            "select_trail_generate_waypoint",
        }
        else {},
        "field_updates": payload.get("field_updates", {})
        if isinstance(payload.get("field_updates", {}), dict)
        else {},
        "selection_payload": payload
        if mapped_operation == "rectangle_group_selection"
        else {},
    }
    target_ref = payload.get("candidate_ref") or payload.get("target_ref")
    target_ref = target_ref or payload.get("feature_ref")
    if isinstance(target_ref, str) and target_ref:
        request_payload["target_ref"] = target_ref
    if isinstance(payload.get("target_refs"), list):
        request_payload["target_refs"] = payload["target_refs"]

    log = append_pretrip_workspace_edit(project_root, request_payload)
    record = log.records[-1].model_dump(mode="json")
    log_path = Path(project_root) / DEFAULT_WORKSPACE_EDIT_LOG_REF
    return {
        "project_id": project_id,
        "artifact_kind": log.artifact_kind,
        "operation": mapped_operation,
        "persisted": True,
        "append_only_log": True,
        "conversion_rule_version": WORKSPACE_EDIT_RULE_VERSION,
        "record": record,
        "candidate": record.get("candidate_payload"),
        "counts": log.counts.model_dump(mode="json"),
        "paths": {
            "workspace_project_root": str(Path(project_root).resolve()),
            "workspace_edit_log": str(log_path),
        },
        "boundary": log.boundary.model_dump(mode="json"),
        "mutation": {
            "source_mutated": False,
            "candidate_artifacts_mutated": False,
            "package_mutated": False,
            "mission_graph_mutated": False,
            "runtime_mutated": False,
            "phase1_runtime_mutated": False,
            "phase2_writeback_performed": False,
            "fixture_files_mutated": False,
            "workspace_files_mutated": True,
            "workspace_edit_log_mutated": True,
        },
    }


def _apply_workspace_candidate_mutation(
    workspace_root: Path,
    project: dict[str, Any],
    request: PreTripWorkspaceEditRequest,
) -> dict[str, Any]:
    checkpoints_path = _workspace_ref_path(
        workspace_root,
        project,
        "checkpoint_candidates_ref",
        "checkpoints",
    )
    retreat_routes_path = _workspace_ref_path(
        workspace_root,
        project,
        "retreat_routes_ref",
        "retreat_routes",
    )
    checkpoints = _load_json_list(checkpoints_path)
    retreat_routes = _load_json_list(retreat_routes_path)
    checkpoint_candidates_mutated = False
    retreat_route_candidates_mutated = False
    candidate: dict[str, Any] | None = None

    if request.operation in ADD_CHECKPOINT_OPERATIONS:
        candidate = _checkpoint_candidate_from_request(
            request,
            project_id=_require_project_string(project, "project_id"),
            checkpoints=checkpoints,
        )
        _reject_duplicate_candidate_id(checkpoints, candidate["candidate_id"])
        checkpoints.append(candidate)
        _replace_json(checkpoints_path, _json_text(checkpoints))
        project["checkpoint_candidate_count"] = len(checkpoints)
        checkpoint_candidates_mutated = True
    elif request.operation in REMOVE_CHECKPOINT_OPERATIONS:
        removed_refs = set(request.selected_target_refs)
        for candidate_ref in removed_refs:
            _reject_core_checkpoint_removal(checkpoints, candidate_ref)
        checkpoints = [
            item for item in checkpoints if item.get("candidate_id") not in removed_refs
        ]
        if len(checkpoints) == _workspace_candidate_counts(workspace_root, project)[
            "checkpoint_candidate_count"
        ]:
            raise ValueError(
                "remove checkpoint target_ref not found in workspace candidates"
            )
        _replace_json(checkpoints_path, _json_text(checkpoints))
        project["checkpoint_candidate_count"] = len(checkpoints)
        checkpoint_candidates_mutated = True
    elif request.operation in ADD_RETREAT_ROUTE_OPERATIONS:
        candidate = _retreat_route_candidate_from_request(
            request,
            project_id=_require_project_string(project, "project_id"),
            retreat_routes=retreat_routes,
        )
        _reject_duplicate_candidate_id(retreat_routes, candidate["candidate_id"])
        retreat_routes.append(candidate)
        _replace_json(retreat_routes_path, _json_text(retreat_routes))
        project["retreat_route_candidate_count"] = len(retreat_routes)
        retreat_route_candidates_mutated = True
    elif request.operation in REMOVE_RETREAT_ROUTE_OPERATIONS:
        removed_refs = set(request.selected_target_refs)
        before_count = len(retreat_routes)
        retreat_routes = [
            item for item in retreat_routes if item.get("candidate_id") not in removed_refs
        ]
        if len(retreat_routes) == before_count:
            raise ValueError(
                "remove retreat route target_ref not found in workspace candidates"
            )
        _replace_json(retreat_routes_path, _json_text(retreat_routes))
        project["retreat_route_candidate_count"] = len(retreat_routes)
        retreat_route_candidates_mutated = True

    return {
        "workspace_candidate_artifacts_mutated": (
            checkpoint_candidates_mutated or retreat_route_candidates_mutated
        ),
        "checkpoint_candidates_mutated": checkpoint_candidates_mutated,
        "retreat_route_candidates_mutated": retreat_route_candidates_mutated,
        "candidate": candidate,
    }


def _checkpoint_candidate_from_request(
    request: PreTripWorkspaceEditRequest,
    *,
    project_id: str,
    checkpoints: list[dict[str, Any]],
) -> dict[str, Any]:
    payload = dict(request.candidate_payload)
    lat = _required_float(payload, "lat")
    lon = _required_float(payload, "lon")
    candidate_id = str(
        payload.get("candidate_id") or _next_candidate_id(checkpoints, f"cp.manual.{project_id}.")
    )
    label = str(payload.get("label") or "Manual waypoint")
    source_refs = request.source_refs or payload.get("source_refs") or [
        "admin.pretrip.workspace_edit"
    ]
    return {
        "candidate_id": candidate_id,
        "label": label,
        "source_refs": source_refs,
        "provenance": payload.get("provenance")
        or [_workspace_edit_provenance(request, source_refs[0])],
        "review_state": payload.get("review_state") or "needs_human_review",
        "confidence": payload.get("confidence") or "low",
        "notes": payload.get("notes")
        or (
            "Workspace-only manual waypoint candidate; requires human review "
            "before any departure handoff."
        ),
        "lat": lat,
        "lon": lon,
        "route_point_index": payload.get("route_point_index"),
        "checkpoint_type": payload.get("checkpoint_type") or "waypoint",
        "arrival_radius_m": float(payload.get("arrival_radius_m") or 30.0),
        "compression_boundary": bool(payload.get("compression_boundary", True)),
    }


def _retreat_route_candidate_from_request(
    request: PreTripWorkspaceEditRequest,
    *,
    project_id: str,
    retreat_routes: list[dict[str, Any]],
) -> dict[str, Any]:
    payload = dict(request.candidate_payload)
    candidate_id = str(
        payload.get("candidate_id")
        or _next_candidate_id(retreat_routes, f"retreat.manual.{project_id}.")
    )
    entry_checkpoint_candidate_id = str(
        payload.get("entry_checkpoint_candidate_id")
        or payload.get("from_checkpoint_candidate_id")
        or ""
    )
    if not entry_checkpoint_candidate_id:
        raise ValueError("add_retreat_route requires entry_checkpoint_candidate_id")
    retreat_type = str(payload.get("retreat_type") or "alternate_route")
    if retreat_type not in {"return_to_entry", "alternate_route", "evacuation_exit"}:
        raise ValueError(f"unsupported retreat_type: {retreat_type}")
    source_refs = request.source_refs or payload.get("source_refs") or [
        entry_checkpoint_candidate_id,
        "admin.pretrip.workspace_edit",
    ]
    return {
        "candidate_id": candidate_id,
        "label": str(payload.get("label") or "Manual retreat route"),
        "source_refs": source_refs,
        "provenance": payload.get("provenance")
        or [_workspace_edit_provenance(request, source_refs[0])],
        "review_state": payload.get("review_state") or "needs_human_review",
        "confidence": payload.get("confidence") or "low",
        "notes": payload.get("notes")
        or (
            "Workspace-only retreat route candidate; geometry and feasibility "
            "require human review."
        ),
        "retreat_type": retreat_type,
        "entry_checkpoint_candidate_id": entry_checkpoint_candidate_id,
        "trigger_checkpoint_candidate_id": payload.get("trigger_checkpoint_candidate_id"),
        "route_point_start_index": payload.get("route_point_start_index"),
        "route_point_end_index": payload.get("route_point_end_index"),
        "reversed_from_primary_route": bool(
            payload.get("reversed_from_primary_route", False)
        ),
        "distance_m": float(payload.get("distance_m") or 0.0),
        "expected_use": payload.get("expected_use") or "retreat",
        "human_review_required": bool(payload.get("human_review_required", True)),
    }


def _workspace_edit_provenance(
    request: PreTripWorkspaceEditRequest,
    source_ref: str,
) -> dict[str, Any]:
    created_at = request.created_at or datetime.now(timezone.utc).isoformat()
    return {
        "source_ref": source_ref,
        "source_kind": "other",
        "uri": "workspace://pretrip/workspace_edit_log",
        "captured_at": created_at,
        "collected_at": created_at,
        "license_note": None,
        "method": f"pretrip_workspace_edit.{request.operation}",
        "notes": "Manual admin workspace edit; candidate evidence only.",
    }


def _workspace_candidate_counts(
    workspace_root: Path,
    project: dict[str, Any],
) -> dict[str, int]:
    checkpoints_path = _workspace_ref_path(
        workspace_root,
        project,
        "checkpoint_candidates_ref",
        "checkpoints",
    )
    retreat_routes_path = _workspace_ref_path(
        workspace_root,
        project,
        "retreat_routes_ref",
        "retreat_routes",
    )
    return {
        "checkpoint_candidate_count": len(_load_json_list(checkpoints_path)),
        "retreat_route_candidate_count": len(_load_json_list(retreat_routes_path)),
    }


def _workspace_ref_path(
    workspace_root: Path,
    project: dict[str, Any],
    project_ref_key: str,
    label: str,
) -> Path:
    ref = project.get(project_ref_key)
    if not isinstance(ref, str) or not ref:
        raise ValueError(f"project.json missing required string field: {project_ref_key}")
    path = workspace_root / ref
    _require_workspace_relative_path(path, workspace_root, label)
    return path


def _load_json_list(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"expected JSON list: {path}")
    return payload


def _write_project(workspace_root: Path, project: dict[str, Any]) -> None:
    project["workspace_edit_log_ref"] = DEFAULT_WORKSPACE_EDIT_LOG_REF
    _replace_json(workspace_root / "project.json", _json_text(project))


def _json_text(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _required_float(payload: dict[str, Any], key: str) -> float:
    try:
        value = float(payload[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"{key} is required and must be numeric") from exc
    if key == "lat" and not -90 <= value <= 90:
        raise ValueError("lat must be between -90 and 90")
    if key == "lon" and not -180 <= value <= 180:
        raise ValueError("lon must be between -180 and 180")
    return value


def _next_candidate_id(candidates: list[dict[str, Any]], prefix: str) -> str:
    used = {str(candidate.get("candidate_id", "")) for candidate in candidates}
    index = 1
    while True:
        candidate_id = f"{prefix}{index:03d}"
        if candidate_id not in used:
            return candidate_id
        index += 1


def _reject_duplicate_candidate_id(
    candidates: list[dict[str, Any]],
    candidate_id: str,
) -> None:
    if any(candidate.get("candidate_id") == candidate_id for candidate in candidates):
        raise ValueError(f"duplicate candidate_id in workspace candidates: {candidate_id}")


def _reject_core_checkpoint_removal(
    checkpoints: list[dict[str, Any]],
    candidate_ref: str,
) -> None:
    for checkpoint in checkpoints:
        if checkpoint.get("candidate_id") != candidate_ref:
            continue
        if checkpoint.get("checkpoint_type") in {"start", "finish"}:
            raise ValueError("start and finish checkpoints cannot be removed")
        return
    raise ValueError(f"checkpoint target_ref not found: {candidate_ref}")


def build_pretrip_workspace_edit_record(
    request: PreTripWorkspaceEditRequest,
    *,
    project_id: str,
    edit_index: int,
    created_at: str,
) -> PreTripWorkspaceEditRecord:
    operation_slug = _ref_slug(request.operation)
    return PreTripWorkspaceEditRecord(
        edit_id=f"workspace_edit.{project_id}.{edit_index:04d}.{operation_slug}",
        operation=request.operation,
        target_kind=_target_kind_for_operation(request.operation),
        target_ref=request.target_ref,
        target_refs=request.target_refs,
        source_refs=request.source_refs,
        reviewer_alias=request.reviewer_alias,
        created_at=created_at,
        summary=request.summary,
        candidate_payload=request.candidate_payload,
        field_updates=request.field_updates,
        selection_payload=request.selection_payload,
    )


def rebuild_pretrip_workspace_edit_log(
    log: PreTripWorkspaceEditLog,
    records: list[PreTripWorkspaceEditRecord],
) -> PreTripWorkspaceEditLog:
    _reject_duplicate_edit_ids(records)
    return PreTripWorkspaceEditLog(
        log_id=log.log_id,
        project_id=log.project_id,
        workspace_edit_log_ref=log.workspace_edit_log_ref,
        source_project_refs=log.source_project_refs,
        records=records,
        counts=_counts_for_records(records),
        boundary=log.boundary,
        notes=log.notes,
    )


def load_pretrip_workspace_edit_log(path: Path | str) -> PreTripWorkspaceEditLog:
    return PreTripWorkspaceEditLog.model_validate_json(
        Path(path).read_text(encoding="utf-8")
    )


def empty_pretrip_workspace_edit_log(project_root: Path | str) -> PreTripWorkspaceEditLog:
    workspace_root = _require_workspace_project_root(project_root)
    project = _load_project(workspace_root)
    project_id = _require_project_string(project, "project_id")
    return _new_log(project_id=project_id, source_project_refs=_source_project_refs(project))


def _load_or_create_log(
    path: Path,
    *,
    project_id: str,
    source_project_refs: dict[str, str],
) -> PreTripWorkspaceEditLog:
    if path.exists():
        log = load_pretrip_workspace_edit_log(path)
        if log.project_id != project_id:
            raise ValueError("workspace edit log project_id does not match workspace")
        return log
    return _new_log(project_id=project_id, source_project_refs=source_project_refs)


def _new_log(
    *,
    project_id: str,
    source_project_refs: dict[str, str],
) -> PreTripWorkspaceEditLog:
    return PreTripWorkspaceEditLog(
        log_id=f"workspace_edit_log.{project_id}.v0",
        project_id=project_id,
        source_project_refs=source_project_refs,
        counts=_counts_for_records([]),
        boundary=PreTripWorkspaceEditBoundary(
            notes=[
                "This append-only log records admin edit-tool operations in a copied local pretrip workspace only.",
                "Operations may update copied workspace candidate artifacts, but packages, MissionGraph outputs, runtime state, Phase 1, and Phase 2 Brain state are not mutated.",
            ],
        ),
        notes=[
            "A later reviewed compiler may consume this workspace state after explicit review.",
        ],
    )


def _counts_for_records(
    records: list[PreTripWorkspaceEditRecord],
) -> PreTripWorkspaceEditCounts:
    by_operation = Counter(record.operation for record in records)
    return PreTripWorkspaceEditCounts(
        edit_count=len(records),
        add_checkpoint_count=by_operation["add_checkpoint"],
        add_waypoint_count=by_operation["add_waypoint"],
        remove_checkpoint_count=by_operation["remove_checkpoint"],
        remove_waypoint_count=by_operation["remove_waypoint"],
        add_retreat_route_count=by_operation["add_retreat_route"],
        remove_retreat_route_count=by_operation["remove_retreat_route"],
        feature_edit_count=by_operation["feature_edit"],
        select_trail_generate_waypoint_count=by_operation[
            "select_trail_generate_waypoint"
        ],
        rectangle_group_selection_count=by_operation["rectangle_group_selection"],
        candidate_only_edit_count=len(records),
    )


def _workspace_edit_log_path(workspace_root: Path) -> Path:
    path = workspace_root / DEFAULT_WORKSPACE_EDIT_LOG_REF
    _require_workspace_relative_path(path, workspace_root, "workspace_edit_log")
    return path


def _target_kind_for_operation(
    operation: WorkspaceEditOperation,
) -> WorkspaceEditTargetKind:
    if operation in ADD_CHECKPOINT_OPERATIONS or operation in REMOVE_CHECKPOINT_OPERATIONS:
        return "checkpoint_waypoint"
    if operation in ADD_RETREAT_ROUTE_OPERATIONS:
        return "retreat_route"
    if operation in REMOVE_RETREAT_ROUTE_OPERATIONS:
        return "retreat_route"
    if operation == "feature_edit":
        return "feature"
    if operation == "rectangle_group_selection":
        return "rectangle_selection"
    return "trail_selection"


def _source_project_refs(project: dict[str, Any]) -> dict[str, str]:
    keys = (
        "checkpoint_candidates_ref",
        "retreat_routes_ref",
        "map_candidates_ref",
        "segment_candidates_ref",
        "package_ref",
        "reviewed_package_ref",
        "runtime_handoff_metadata_ref",
    )
    return {
        key: value
        for key in keys
        if isinstance(value := project.get(key), str) and value
    }


def _load_project(workspace_root: Path) -> dict[str, Any]:
    project_path = workspace_root / "project.json"
    if not project_path.is_file():
        raise FileNotFoundError(f"missing workspace project.json: {project_path}")
    payload = json.loads(project_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("project.json must contain a JSON object")
    return payload


def _require_workspace_project_root(project_root: Path | str) -> Path:
    root = Path(project_root).expanduser()
    if not root.is_dir():
        raise FileNotFoundError(f"workspace project root does not exist: {root}")
    if not (root / "project.json").is_file():
        raise FileNotFoundError(f"missing workspace project.json: {root / 'project.json'}")

    resolved = root.resolve()
    try:
        resolved.relative_to(REPO_FIXTURE_ROOT.resolve())
    except ValueError:
        return root
    raise ValueError(
        "workspace edit log must be written to a copied workspace, not repo fixtures"
    )


def _require_project_string(project: dict[str, Any], key: str) -> str:
    value = project.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"project.json missing required string field: {key}")
    return value


def _require_workspace_relative_path(path: Path, workspace_root: Path, label: str) -> None:
    try:
        path.resolve().relative_to(workspace_root.resolve())
    except ValueError as exc:
        raise ValueError(f"{label} must resolve inside the project workspace") from exc


def _reject_duplicate_edit_ids(records: list[PreTripWorkspaceEditRecord]) -> None:
    seen: set[str] = set()
    for record in records:
        if record.edit_id in seen:
            raise ValueError(f"duplicate workspace edit_id: {record.edit_id}")
        seen.add(record.edit_id)


def _assert_candidate_only_payload(value: object) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in FORBIDDEN_TRUE_KEYS and item is True:
                raise ValueError(f"workspace edit log rejects {key}=true")
            _assert_candidate_only_payload(item)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _assert_candidate_only_payload(item)
        return
    if isinstance(value, str):
        _reject_forbidden_payload_fragment(value)


def _reject_forbidden_payload_fragment(value: str) -> None:
    lowered = value.lower()
    for fragment in FORBIDDEN_PAYLOAD_FRAGMENTS:
        if fragment.lower() in lowered:
            raise ValueError(f"forbidden workspace edit payload fragment: {fragment}")


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
