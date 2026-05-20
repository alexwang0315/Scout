from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pretrip_expert_contribution import (
    ContributionOperation,
    ContributionTargetKind,
    ExpertContributionLog,
    ExpertContributionRecord,
    load_expert_contribution_log,
)


DEFAULT_APPLY_PLAN_REF = "outputs/expert_contribution_apply_plan.json"
DEFAULT_EXPERT_CONTRIBUTION_LOG_REF = "outputs/expert_contribution_log.json"
DEFAULT_WORKSPACE_APPLY_RESULT_REF = "outputs/expert_contribution_workspace_apply_result.json"
REPO_FIXTURE_PROJECTS_ROOT = (
    Path(__file__).resolve().parent / "tests" / "fixtures" / "pretrip" / "projects"
)


class ExpertContributionApplyPlanModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExpertContributionApplyBoundary(ExpertContributionApplyPlanModel):
    workspace_only: Literal[True] = True
    would_apply_only: Literal[True] = True
    source_artifact_mutation_allowed: Literal[False] = False
    candidate_artifact_mutation_allowed: Literal[False] = False
    external_import_queue_mutation_allowed: Literal[False] = False
    package_mutation_allowed: Literal[False] = False
    mission_graph_mutation_allowed: Literal[False] = False
    compiles_mission_graph: Literal[False] = False
    runtime_mutation_allowed: Literal[False] = False
    phase1_runtime_mutation_allowed: Literal[False] = False
    phase2_brain_writeback_allowed: Literal[False] = False
    external_api_calls_made: Literal[False] = False
    raw_payloads_embedded: Literal[False] = False
    repo_fixture_write_allowed: Literal[False] = False
    notes: list[str] = Field(default_factory=list)


class ExpertContributionWorkspaceApplyBoundary(ExpertContributionApplyPlanModel):
    workspace_only: Literal[True] = True
    would_apply_only: Literal[False] = False
    source_artifact_mutation_allowed: Literal[False] = False
    workspace_candidate_artifact_mutation_allowed: Literal[True] = True
    workspace_external_import_queue_mutation_allowed: Literal[True] = True
    repo_fixture_write_allowed: Literal[False] = False
    package_mutation_allowed: Literal[False] = False
    mission_graph_mutation_allowed: Literal[False] = False
    compiles_mission_graph: Literal[False] = False
    runtime_mutation_allowed: Literal[False] = False
    phase1_runtime_mutation_allowed: Literal[False] = False
    phase2_brain_writeback_allowed: Literal[False] = False
    external_api_calls_made: Literal[False] = False
    raw_payloads_embedded: Literal[False] = False
    notes: list[str] = Field(default_factory=list)


class ExpertContributionApplyCounts(ExpertContributionApplyPlanModel):
    contribution_count: int = Field(ge=0)
    planned_operation_count: int = Field(ge=0)
    accepted_count: int = Field(ge=0)
    intended_count: int = Field(ge=0)
    skipped_count: int = Field(ge=0)
    candidate_set_operation_count: int = Field(ge=0)
    external_import_operation_count: int = Field(ge=0)
    source_artifact_mutation_count: Literal[0] = 0
    package_mutation_count: Literal[0] = 0
    mission_graph_mutation_count: Literal[0] = 0
    runtime_mutation_count: Literal[0] = 0
    phase2_brain_writeback_count: Literal[0] = 0
    raw_payload_count: Literal[0] = 0


class ExpertContributionWorkspaceApplyCounts(ExpertContributionApplyPlanModel):
    planned_operation_count: int = Field(ge=0)
    applied_operation_count: int = Field(ge=0)
    skipped_operation_count: int = Field(ge=0)
    checkpoint_candidate_append_count: int = Field(ge=0)
    retreat_route_update_count: int = Field(ge=0)
    external_import_request_append_count: int = Field(ge=0)
    package_mutation_count: Literal[0] = 0
    mission_graph_mutation_count: Literal[0] = 0
    runtime_mutation_count: Literal[0] = 0
    phase1_runtime_mutation_count: Literal[0] = 0
    phase2_brain_writeback_count: Literal[0] = 0
    raw_payload_count: Literal[0] = 0


class ExpertContributionPlannedOperation(ExpertContributionApplyPlanModel):
    planned_operation_id: str
    contribution_id: str
    review_state: Literal["accepted", "needs_human_review"]
    operation: ContributionOperation
    target_kind: ContributionTargetKind
    target_ref: str
    target_artifact_ref: str
    target_scope: Literal["candidate_set", "external_import_queue"]
    source_surface: Literal["admin_candidate_set", "admin_external_import_queue"]
    evidence_status: Literal[
        "admin_claim",
        "community_report_reference",
        "field_observation_pending",
    ]
    summary: str
    rationale: str
    would_apply_to_candidate_set: bool
    would_apply_to_external_import_queue: bool
    mutates_target_artifact: Literal[False] = False
    embeds_raw_payload: Literal[False] = False
    notes: list[str] = Field(default_factory=list)


class ExpertContributionSkippedRecord(ExpertContributionApplyPlanModel):
    contribution_id: str
    review_state: Literal["proposed", "rejected"]
    reason: Literal["not_accepted_or_intended"] = "not_accepted_or_intended"


class ExpertContributionAppliedOperation(ExpertContributionApplyPlanModel):
    planned_operation_id: str
    contribution_id: str
    operation: ContributionOperation
    target_kind: ContributionTargetKind
    target_ref: str
    target_artifact_ref: str
    applied: bool
    result_ref: str | None = None
    before_ref: str | None = None
    after_ref: str | None = None
    summary: str
    provenance: dict[str, Any]


class ExpertContributionWorkspaceApplyResult(ExpertContributionApplyPlanModel):
    result_id: str
    artifact_kind: Literal["pretrip_expert_contribution_workspace_apply_result"] = (
        "pretrip_expert_contribution_workspace_apply_result"
    )
    project_id: str
    apply_plan_ref: str
    applied_operations: list[ExpertContributionAppliedOperation]
    counts: ExpertContributionWorkspaceApplyCounts
    boundary: ExpertContributionWorkspaceApplyBoundary = Field(
        default_factory=ExpertContributionWorkspaceApplyBoundary
    )
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_workspace_apply_boundary(self) -> "ExpertContributionWorkspaceApplyResult":
        if self.counts.planned_operation_count != len(self.applied_operations):
            raise ValueError("planned_operation_count must match applied operations")
        if self.counts.applied_operation_count != sum(
            operation.applied for operation in self.applied_operations
        ):
            raise ValueError("applied_operation_count must match applied operations")
        if self.counts.skipped_operation_count != sum(
            not operation.applied for operation in self.applied_operations
        ):
            raise ValueError("skipped_operation_count must match applied operations")
        _assert_no_runtime_or_raw_payload_fragments(self.model_dump(mode="json"))
        return self

    def to_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n"


class ExpertContributionApplyPlan(ExpertContributionApplyPlanModel):
    plan_id: str
    artifact_kind: Literal["pretrip_expert_contribution_apply_plan"] = (
        "pretrip_expert_contribution_apply_plan"
    )
    project_id: str
    expert_contribution_log_ref: str
    planned_operations: list[ExpertContributionPlannedOperation]
    skipped_records: list[ExpertContributionSkippedRecord] = Field(default_factory=list)
    counts: ExpertContributionApplyCounts
    boundary: ExpertContributionApplyBoundary = Field(
        default_factory=ExpertContributionApplyBoundary
    )
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_apply_plan_boundary(self) -> "ExpertContributionApplyPlan":
        if self.counts.planned_operation_count != len(self.planned_operations):
            raise ValueError("planned_operation_count must match planned operations")
        if self.counts.skipped_count != len(self.skipped_records):
            raise ValueError("skipped_count must match skipped records")
        if self.counts.contribution_count != (
            len(self.planned_operations) + len(self.skipped_records)
        ):
            raise ValueError("contribution_count must match planned and skipped records")
        if self.counts.candidate_set_operation_count != sum(
            operation.would_apply_to_candidate_set for operation in self.planned_operations
        ):
            raise ValueError("candidate_set_operation_count must match planned operations")
        if self.counts.external_import_operation_count != sum(
            operation.would_apply_to_external_import_queue
            for operation in self.planned_operations
        ):
            raise ValueError("external_import_operation_count must match planned operations")
        if self.counts.accepted_count != sum(
            operation.review_state == "accepted" for operation in self.planned_operations
        ):
            raise ValueError("accepted_count must match planned operations")
        if self.counts.intended_count != sum(
            operation.review_state == "needs_human_review"
            for operation in self.planned_operations
        ):
            raise ValueError("intended_count must match planned operations")
        _assert_no_runtime_or_raw_payload_fragments(self.model_dump(mode="json"))
        return self

    def to_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n"


def build_expert_contribution_apply_plan(
    *,
    project_id: str,
    expert_contribution_log_ref: str,
    contribution_log: ExpertContributionLog,
) -> ExpertContributionApplyPlan:
    planned_operations = [
        _planned_operation(record)
        for record in contribution_log.records
        if record.review_state in {"accepted", "needs_human_review"}
    ]
    skipped_records = [
        ExpertContributionSkippedRecord(
            contribution_id=record.contribution_id,
            review_state=record.review_state,
        )
        for record in contribution_log.records
        if record.review_state in {"proposed", "rejected"}
    ]
    counts_by_state = Counter(operation.review_state for operation in planned_operations)

    return ExpertContributionApplyPlan(
        plan_id=f"expert_contribution_apply_plan.{project_id}.v0",
        project_id=project_id,
        expert_contribution_log_ref=expert_contribution_log_ref,
        planned_operations=planned_operations,
        skipped_records=skipped_records,
        counts=ExpertContributionApplyCounts(
            contribution_count=len(contribution_log.records),
            planned_operation_count=len(planned_operations),
            accepted_count=counts_by_state["accepted"],
            intended_count=counts_by_state["needs_human_review"],
            skipped_count=len(skipped_records),
            candidate_set_operation_count=sum(
                operation.would_apply_to_candidate_set
                for operation in planned_operations
            ),
            external_import_operation_count=sum(
                operation.would_apply_to_external_import_queue
                for operation in planned_operations
            ),
        ),
        boundary=ExpertContributionApplyBoundary(
            notes=[
                "Apply plan is a copied workspace metadata artifact only.",
                "Planned operations point at accepted or review-gated intended expert contributions without mutating source artifacts, candidate files, import queues, PreTripPackage, MissionGraph outputs, runtime state, or Phase 2 Brain state.",
                "Records with proposed or rejected review state are skipped and retained only as metadata pointers.",
            ],
        ),
        notes=[
            "This artifact is the handoff hook a later reviewed workspace applier can consume.",
            "It intentionally records no patch payloads and performs no network fetches.",
        ],
    )


def build_expert_contribution_apply_plan_from_workspace(
    project_root: Path | str,
    *,
    expert_contribution_log_ref: str = DEFAULT_EXPERT_CONTRIBUTION_LOG_REF,
) -> ExpertContributionApplyPlan:
    project_path = _resolve_workspace_project_root(project_root)
    contribution_log = load_expert_contribution_log(
        project_path / expert_contribution_log_ref
    )
    return build_expert_contribution_apply_plan(
        project_id=contribution_log.project_id,
        expert_contribution_log_ref=expert_contribution_log_ref,
        contribution_log=contribution_log,
    )


def write_expert_contribution_apply_plan(
    project_root: Path | str,
    *,
    output_ref: str = DEFAULT_APPLY_PLAN_REF,
    expert_contribution_log_ref: str = DEFAULT_EXPERT_CONTRIBUTION_LOG_REF,
) -> ExpertContributionApplyPlan:
    project_path = _resolve_workspace_project_root(project_root)
    plan = build_expert_contribution_apply_plan_from_workspace(
        project_path,
        expert_contribution_log_ref=expert_contribution_log_ref,
    )
    destination = project_path / output_ref
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(plan.to_json(), encoding="utf-8")
    return plan


def apply_expert_contributions_to_workspace(
    project_root: Path | str,
    *,
    apply_plan_ref: str = DEFAULT_APPLY_PLAN_REF,
    output_ref: str = DEFAULT_WORKSPACE_APPLY_RESULT_REF,
) -> ExpertContributionWorkspaceApplyResult:
    project_path = _resolve_workspace_project_root(project_root)
    apply_plan_path = project_path / apply_plan_ref
    plan = (
        load_expert_contribution_apply_plan(apply_plan_path)
        if apply_plan_path.is_file()
        else write_expert_contribution_apply_plan(project_path, output_ref=apply_plan_ref)
    )

    checkpoint_ref = "candidates/checkpoints.json"
    retreat_ref = "candidates/retreat_routes.json"
    external_import_ref = "outputs/external_import_queue.json"
    checkpoints = _load_json_list(project_path / checkpoint_ref)
    retreat_routes = _load_json_list(project_path / retreat_ref)
    external_import_queue = _load_json_dict(project_path / external_import_ref)
    applied_operations: list[ExpertContributionAppliedOperation] = []

    for operation in plan.planned_operations:
        if (
            operation.operation == ContributionOperation.ADD_CANDIDATE
            and operation.target_kind == ContributionTargetKind.CHECKPOINT_CANDIDATE
        ):
            checkpoints.append(_checkpoint_candidate_from_operation(operation))
            applied_operations.append(
                _applied_operation(
                    operation,
                    result_ref=operation.target_artifact_ref,
                    before_ref=None,
                    after_ref=operation.target_ref,
                )
            )
        elif (
            operation.operation == ContributionOperation.UPDATE_CANDIDATE
            and operation.target_kind == ContributionTargetKind.RETREAT_ROUTE_CANDIDATE
        ):
            _apply_retreat_route_update(retreat_routes, operation)
            applied_operations.append(
                _applied_operation(
                    operation,
                    result_ref=operation.target_artifact_ref,
                    before_ref=operation.target_ref,
                    after_ref=operation.target_ref,
                )
            )
        elif (
            operation.operation == ContributionOperation.ADD_IMPORT_REQUEST
            and operation.target_kind == ContributionTargetKind.EXTERNAL_IMPORT_REQUEST
        ):
            external_import_queue.setdefault("requests", []).append(
                _external_import_request_from_operation(operation)
            )
            _refresh_external_import_counts(external_import_queue)
            applied_operations.append(
                _applied_operation(
                    operation,
                    result_ref=operation.target_artifact_ref,
                    before_ref=None,
                    after_ref=operation.target_ref,
                )
            )
        else:
            applied_operations.append(
                _applied_operation(
                    operation,
                    result_ref=None,
                    before_ref=None,
                    after_ref=None,
                    applied=False,
                    summary="Operation skipped by workspace applier because this operation kind is not implemented.",
                )
            )

    _write_json(project_path / checkpoint_ref, checkpoints)
    _write_json(project_path / retreat_ref, retreat_routes)
    _write_json(project_path / external_import_ref, external_import_queue)
    result = _workspace_apply_result(
        project_id=plan.project_id,
        apply_plan_ref=apply_plan_ref,
        applied_operations=applied_operations,
    )
    _write_text(project_path / output_ref, result.to_json())
    return result


def load_expert_contribution_apply_plan(path: Path | str) -> ExpertContributionApplyPlan:
    return ExpertContributionApplyPlan.model_validate_json(
        Path(path).read_text(encoding="utf-8")
    )


def load_expert_contribution_workspace_apply_result(
    path: Path | str,
) -> ExpertContributionWorkspaceApplyResult:
    return ExpertContributionWorkspaceApplyResult.model_validate_json(
        Path(path).read_text(encoding="utf-8")
    )


def _planned_operation(
    record: ExpertContributionRecord,
) -> ExpertContributionPlannedOperation:
    target_scope = (
        "external_import_queue"
        if record.applies_to_external_import_queue
        else "candidate_set"
    )
    return ExpertContributionPlannedOperation(
        planned_operation_id=f"planned_operation.{record.contribution_id}",
        contribution_id=record.contribution_id,
        review_state=record.review_state,
        operation=record.operation,
        target_kind=record.target_kind,
        target_ref=record.target_ref,
        target_artifact_ref=record.target_artifact_ref,
        target_scope=target_scope,
        source_surface=record.source_surface,
        evidence_status=record.evidence_status,
        summary=record.summary,
        rationale=record.rationale,
        would_apply_to_candidate_set=record.applies_to_candidate_set,
        would_apply_to_external_import_queue=record.applies_to_external_import_queue,
        notes=[
            "Candidate-only metadata pointer; no target artifact is patched by this plan."
        ],
    )


def _workspace_apply_result(
    *,
    project_id: str,
    apply_plan_ref: str,
    applied_operations: list[ExpertContributionAppliedOperation],
) -> ExpertContributionWorkspaceApplyResult:
    applied = [operation for operation in applied_operations if operation.applied]
    return ExpertContributionWorkspaceApplyResult(
        result_id=f"expert_contribution_workspace_apply_result.{project_id}.v0",
        project_id=project_id,
        apply_plan_ref=apply_plan_ref,
        applied_operations=applied_operations,
        counts=ExpertContributionWorkspaceApplyCounts(
            planned_operation_count=len(applied_operations),
            applied_operation_count=len(applied),
            skipped_operation_count=len(applied_operations) - len(applied),
            checkpoint_candidate_append_count=sum(
                operation.target_kind == ContributionTargetKind.CHECKPOINT_CANDIDATE
                and operation.applied
                for operation in applied_operations
            ),
            retreat_route_update_count=sum(
                operation.target_kind == ContributionTargetKind.RETREAT_ROUTE_CANDIDATE
                and operation.applied
                for operation in applied_operations
            ),
            external_import_request_append_count=sum(
                operation.target_kind == ContributionTargetKind.EXTERNAL_IMPORT_REQUEST
                and operation.applied
                for operation in applied_operations
            ),
        ),
        boundary=ExpertContributionWorkspaceApplyBoundary(
            notes=[
                "This result mutates only copied workspace candidate/import metadata files.",
                "Repo fixtures, source artifacts, PreTripPackage, MissionGraph outputs, runtime state, Phase 1, and Phase 2 Brain state remain untouched.",
            ],
        ),
        notes=[
            "Workspace-applied expert contributions remain planning candidates until a later reviewed package/compiler flow consumes them.",
        ],
    )


def _checkpoint_candidate_from_operation(
    operation: ExpertContributionPlannedOperation,
) -> dict[str, Any]:
    return {
        "arrival_radius_m": 30.0,
        "candidate_id": operation.target_ref,
        "checkpoint_type": "route_progress",
        "compression_boundary": False,
        "confidence": "expert_contribution_candidate",
        "label": "Expert-added trail condition checkpoint",
        "lat": None,
        "lon": None,
        "notes": operation.summary,
        "provenance": [_operation_provenance(operation)],
        "review_state": "needs_human_review",
        "route_point_index": None,
        "source_refs": [operation.contribution_id],
    }


def _apply_retreat_route_update(
    retreat_routes: list[Any],
    operation: ExpertContributionPlannedOperation,
) -> None:
    for route in retreat_routes:
        if isinstance(route, dict) and route.get("candidate_id") == operation.target_ref:
            route["review_state"] = "needs_human_review"
            route["notes"] = f"{route.get('notes', '')} Expert update: {operation.summary}".strip()
            route.setdefault("source_refs", []).append(operation.contribution_id)
            route.setdefault("provenance", []).append(_operation_provenance(operation))
            return
    raise ValueError(f"retreat route candidate not found: {operation.target_ref}")


def _external_import_request_from_operation(
    operation: ExpertContributionPlannedOperation,
) -> dict[str, Any]:
    return {
        "artifact_candidate_only": True,
        "authoritative_until_reviewed": False,
        "crawler_enabled": False,
        "derived_measurement_candidate": False,
        "intended_treatment": [
            "planning_reference",
            "model_interpretation_input",
            "human_review_required",
        ],
        "network_call_count": 0,
        "notes": operation.rationale,
        "observed_fact_candidate": False,
        "raw_payload_embedded": False,
        "request_id": operation.target_ref,
        "requested_artifact_kind": "planning_reference",
        "review_requirement": "human_review_required",
        "source_id": operation.contribution_id,
        "source_kind": "community_report_reference",
        "source_url": None,
        "status": "pending",
        "title": operation.summary,
    }


def _applied_operation(
    operation: ExpertContributionPlannedOperation,
    *,
    result_ref: str | None,
    before_ref: str | None,
    after_ref: str | None,
    applied: bool = True,
    summary: str | None = None,
) -> ExpertContributionAppliedOperation:
    return ExpertContributionAppliedOperation(
        planned_operation_id=operation.planned_operation_id,
        contribution_id=operation.contribution_id,
        operation=operation.operation,
        target_kind=operation.target_kind,
        target_ref=operation.target_ref,
        target_artifact_ref=operation.target_artifact_ref,
        applied=applied,
        result_ref=result_ref,
        before_ref=before_ref,
        after_ref=after_ref,
        summary=summary or "Applied to copied workspace metadata only.",
        provenance=_operation_provenance(operation),
    )


def _operation_provenance(operation: ExpertContributionPlannedOperation) -> dict[str, Any]:
    return {
        "method": "pretrip_expert_contribution_apply_plan.apply_expert_contributions_to_workspace",
        "source_ref": operation.contribution_id,
        "source_kind": "expert_contribution",
        "notes": "Workspace-only candidate/import queue update; not final package, MissionGraph, runtime, or Brain state.",
    }


def _refresh_external_import_counts(queue: dict[str, Any]) -> None:
    requests = queue.get("requests", [])
    pending = sum(
        1
        for request in requests
        if isinstance(request, dict) and request.get("status") == "pending"
    )
    counts = queue.setdefault("counts", {})
    counts["request_count"] = len(requests)
    counts["pending_count"] = pending
    counts["crawler_enabled_count"] = sum(
        1
        for request in requests
        if isinstance(request, dict) and request.get("crawler_enabled") is True
    )
    counts["network_call_count"] = sum(
        int(request.get("network_call_count", 0))
        for request in requests
        if isinstance(request, dict)
    )
    counts["observed_fact_count"] = 0
    counts["raw_payloads_embedded"] = False


def _resolve_workspace_project_root(project_root: Path | str) -> Path:
    path = Path(project_root).resolve()
    if (path / "project.json").exists():
        project_path = path
    elif path.name == "project.json" and path.exists():
        project_path = path.parent
    else:
        raise FileNotFoundError(f"could not find workspace project.json under {path}")

    if _is_relative_to(project_path, REPO_FIXTURE_PROJECTS_ROOT.resolve()):
        raise ValueError("expert contribution apply plan must be written only to a copied workspace")
    return project_path


def _load_json_list(path: Path) -> list[Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"{path} must contain a JSON list")
    return payload


def _load_json_dict(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _write_json(path: Path, payload: Any) -> None:
    _write_text(path, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _write_text(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _assert_no_runtime_or_raw_payload_fragments(payload: Any) -> None:
    sanitized = _strip_allowed_boundary_keys(payload)
    serialized = json.dumps(sanitized, ensure_ascii=False, sort_keys=True)
    forbidden_fragments = (
        "/safety",
        "Phase1IncidentBridge",
        "SCOUT_PHASE2_INCIDENT_BRIDGE",
        "Phase2Brain",
        "ObservedFact",
        "write_observed_fact",
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
        "raw_html",
        "snapshot_body",
        "raw_dtm",
        "raw_photo",
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
            if key not in {
                "embeds_raw_payload",
                "raw_payloads_embedded",
                "raw_payload_count",
            }
        }
    if isinstance(payload, list):
        return [_strip_allowed_boundary_keys(item) for item in payload]
    return payload
