from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections import Counter
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from pretrip_departure_gate import (
    DepartureApprovalRecord,
    DepartureGateBoundary,
    DepartureGateCounts,
    DepartureGateFinding,
    DepartureGateSeverity,
    DepartureGateStatus,
    PreTripDepartureGateManifest,
)


DEFAULT_DEPARTURE_GATE_RESOLUTION_LOG_REF = (
    "reviews/departure_gate_resolution_log.json"
)


class DepartureGateResolutionAction(StrEnum):
    WARNING_OVERRIDE = "warning_override"
    RESOLVED_BY_REVIEW = "resolved_by_review"


class DepartureGateResolutionModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DepartureGateResolutionRecord(DepartureGateResolutionModel):
    resolution_id: str
    source_departure_gate_manifest_id: str
    project_id: str
    finding_id: str
    finding_rule_id: str
    finding_severity: Literal["warning"]
    finding_source_ref: str
    finding_source_artifact_kind: str
    finding_message_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    action: DepartureGateResolutionAction
    reason: str = Field(min_length=12)
    reviewer_alias: str = Field(min_length=1)
    decided_at: str
    append_only: Literal[True] = True
    local_workspace_only: Literal[True] = True
    metadata_only: Literal[True] = True
    source_mutation_allowed: Literal[False] = False
    package_mutation_allowed: Literal[False] = False
    mission_graph_mutation_allowed: Literal[False] = False
    runtime_mutation_allowed: Literal[False] = False
    phase1_runtime_mutation_allowed: Literal[False] = False
    phase2_writeback_allowed: Literal[False] = False
    raw_payloads_embedded: Literal[False] = False

    @field_validator("decided_at")
    @classmethod
    def require_iso_decided_at(cls, value: str) -> str:
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("decided_at must be an ISO-8601 datetime") from exc
        return value

    @model_validator(mode="after")
    def enforce_metadata_boundary(self) -> "DepartureGateResolutionRecord":
        _assert_no_runtime_or_raw_payload_fragments(self.model_dump(mode="json"))
        return self


class DepartureGateResolutionCounts(DepartureGateResolutionModel):
    resolution_count: int = Field(ge=0)
    warning_override_count: int = Field(ge=0)
    resolved_by_review_count: int = Field(ge=0)
    blocker_resolution_attempt_count: Literal[0] = 0
    source_mutation_count: Literal[0] = 0
    package_mutation_count: Literal[0] = 0
    mission_graph_mutation_count: Literal[0] = 0
    runtime_mutation_count: Literal[0] = 0
    phase1_runtime_mutation_count: Literal[0] = 0
    phase2_writeback_count: Literal[0] = 0
    raw_payload_count: Literal[0] = 0


class DepartureGateResolutionBoundary(DepartureGateResolutionModel):
    append_only: Literal[True] = True
    local_workspace_only: Literal[True] = True
    metadata_only: Literal[True] = True
    repo_fixture_write_allowed: Literal[False] = False
    source_mutation_allowed: Literal[False] = False
    package_mutation_allowed: Literal[False] = False
    mission_graph_mutation_allowed: Literal[False] = False
    runtime_mutation_allowed: Literal[False] = False
    phase1_runtime_mutation_allowed: Literal[False] = False
    phase2_writeback_allowed: Literal[False] = False
    raw_payloads_embedded: Literal[False] = False
    notes: tuple[str, ...] = Field(default_factory=tuple)


class DepartureGateResolutionLog(DepartureGateResolutionModel):
    log_id: str
    artifact_kind: Literal["pretrip_departure_gate_resolution_log"] = (
        "pretrip_departure_gate_resolution_log"
    )
    project_id: str
    source_departure_gate_manifest_id: str
    records: tuple[DepartureGateResolutionRecord, ...] = Field(default_factory=tuple)
    counts: DepartureGateResolutionCounts
    boundary: DepartureGateResolutionBoundary = Field(
        default_factory=DepartureGateResolutionBoundary
    )
    notes: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def enforce_log_boundary(self) -> "DepartureGateResolutionLog":
        _reject_duplicate_finding_ids(self.records)
        _reject_duplicate_resolution_ids(self.records)
        if self.counts.resolution_count != len(self.records):
            raise ValueError("resolution_count must match records")
        action_counts = Counter(record.action for record in self.records)
        if (
            self.counts.warning_override_count
            != action_counts[DepartureGateResolutionAction.WARNING_OVERRIDE]
        ):
            raise ValueError("warning_override_count must match records")
        if (
            self.counts.resolved_by_review_count
            != action_counts[DepartureGateResolutionAction.RESOLVED_BY_REVIEW]
        ):
            raise ValueError("resolved_by_review_count must match records")
        _assert_no_runtime_or_raw_payload_fragments(self.model_dump(mode="json"))
        return self

    def to_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n"


def build_departure_gate_resolution_record(
    gate: PreTripDepartureGateManifest,
    finding: DepartureGateFinding,
    *,
    action: DepartureGateResolutionAction,
    reason: str,
    reviewer_alias: str,
    decided_at: str,
) -> DepartureGateResolutionRecord:
    if finding.severity == DepartureGateSeverity.BLOCKER:
        raise ValueError("cannot resolve blocker through departure gate resolution")
    action = DepartureGateResolutionAction(action)
    finding_message_hash = hashlib.sha256(finding.message.encode("utf-8")).hexdigest()
    return DepartureGateResolutionRecord(
        resolution_id=(
            f"departure_gate_resolution.{gate.project_id}.{_ref_slug(finding.finding_id)}"
        ),
        source_departure_gate_manifest_id=gate.manifest_id,
        project_id=gate.project_id,
        finding_id=finding.finding_id,
        finding_rule_id=finding.rule_id,
        finding_severity="warning",
        finding_source_ref=finding.source_ref,
        finding_source_artifact_kind=finding.source_artifact_kind,
        finding_message_sha256=finding_message_hash,
        action=action,
        reason=reason,
        reviewer_alias=reviewer_alias,
        decided_at=decided_at,
    )


def build_chilai_warning_resolution_log(
    gate: PreTripDepartureGateManifest,
    *,
    reviewer_alias: str,
    decided_at: str,
    finding_ids: list[str] | tuple[str, ...] | None = None,
) -> DepartureGateResolutionLog:
    selected_finding_ids = set(finding_ids) if finding_ids is not None else None
    records = [
        build_departure_gate_resolution_record(
            gate,
            finding,
            action=DepartureGateResolutionAction.WARNING_OVERRIDE,
            reason=_default_warning_resolution_reason(finding),
            reviewer_alias=reviewer_alias,
            decided_at=decided_at,
        )
        for finding in gate.findings
        if finding.severity == DepartureGateSeverity.WARNING
        and (selected_finding_ids is None or finding.finding_id in selected_finding_ids)
    ]
    return rebuild_departure_gate_resolution_log(
        DepartureGateResolutionLog(
            log_id=f"departure_gate_resolution_log.{gate.project_id}.v0",
            project_id=gate.project_id,
            source_departure_gate_manifest_id=gate.manifest_id,
            counts=DepartureGateResolutionCounts(
                resolution_count=0,
                warning_override_count=0,
                resolved_by_review_count=0,
            ),
            boundary=DepartureGateResolutionBoundary(
                notes=(
                    "Departure Gate Resolution / 出發關卡處理紀錄 is workspace-only.",
                    "Warnings can be accepted with explicit reviewer reason; hard blockers cannot.",
                )
            ),
        ),
        records,
    )


def apply_departure_gate_resolutions(
    gate: PreTripDepartureGateManifest,
    resolution_log: DepartureGateResolutionLog | dict[str, Any],
    *,
    approved_by: str,
    approved_at: str,
) -> PreTripDepartureGateManifest:
    log = DepartureGateResolutionLog.model_validate(resolution_log)
    _validate_log_matches_gate(gate, log)
    finding_by_id = {finding.finding_id: finding for finding in gate.findings}
    resolved_ids = {record.finding_id for record in log.records}
    for finding_id in resolved_ids:
        if finding_id not in finding_by_id:
            raise ValueError(f"resolution references unknown finding_id: {finding_id}")
        if finding_by_id[finding_id].severity == DepartureGateSeverity.BLOCKER:
            raise ValueError("cannot apply resolution to blocker")

    unresolved_findings = [
        finding for finding in gate.findings if finding.finding_id not in resolved_ids
    ]
    severity_counts = Counter(finding.severity for finding in unresolved_findings)
    hard_blocker_count = sum(
        1
        for finding in unresolved_findings
        if finding.severity == DepartureGateSeverity.BLOCKER
        and not finding.blocker_override_allowed
    )
    status = _status_for(unresolved_findings)
    final_generation_allowed = status == DepartureGateStatus.PASSED

    return PreTripDepartureGateManifest(
        manifest_id=f"{gate.manifest_id}.resolved",
        project_id=gate.project_id,
        status=status,
        planning_review_profile_ref=gate.planning_review_profile_ref,
        route_class=gate.route_class,
        trip_classification_zh=gate.trip_classification_zh,
        input_refs=gate.input_refs,
        findings=unresolved_findings,
        approval=DepartureApprovalRecord(
            approval_id=f"{gate.approval.approval_id}.resolved",
            status=status,
            approval_granted=status == DepartureGateStatus.PASSED,
            project_id=gate.approval.project_id,
            profile_id=gate.approval.profile_id,
            profile_display_name_zh=gate.approval.profile_display_name_zh,
            approved_by=approved_by if status == DepartureGateStatus.PASSED else None,
            approved_at=approved_at if status == DepartureGateStatus.PASSED else None,
            reviewed_package_ref=gate.approval.reviewed_package_ref,
            reviewed_package_hash=gate.approval.reviewed_package_hash,
            mission_graph_candidate_ref=gate.approval.mission_graph_candidate_ref,
            mission_graph_candidate_hash=gate.approval.mission_graph_candidate_hash,
            final_mission_graph_generation_allowed=final_generation_allowed,
            unresolved_warnings=[
                finding
                for finding in unresolved_findings
                if finding.severity == DepartureGateSeverity.WARNING
            ],
            blockers=[
                finding
                for finding in unresolved_findings
                if finding.severity == DepartureGateSeverity.BLOCKER
            ],
            override_reasons=[
                f"{record.finding_id}: {record.reason}" for record in log.records
            ],
        ),
        counts=DepartureGateCounts(
            input_ref_count=len(gate.input_refs),
            warning_count=severity_counts[DepartureGateSeverity.WARNING],
            blocker_count=severity_counts[DepartureGateSeverity.BLOCKER],
            override_reason_count=len(log.records),
            unresolved_warning_count=severity_counts[DepartureGateSeverity.WARNING],
            hard_blocker_count=hard_blocker_count,
        ),
        boundary=DepartureGateBoundary(
            final_mission_graph_generation_allowed=final_generation_allowed,
            notes=(
                *gate.boundary.notes,
                "Resolution log / 處理紀錄 can move hold to pass only after every warning is reviewed.",
                "Runtime Handoff / 現場 runtime 交接 is still a separate explicit step.",
            ),
        ),
        notes=(
            *gate.notes,
            f"Applied departure gate resolution log {log.log_id}.",
        ),
    )


def append_departure_gate_resolution(
    workspace_root: Path | str,
    gate: PreTripDepartureGateManifest,
    *,
    finding_id: str,
    action: DepartureGateResolutionAction,
    reason: str,
    reviewer_alias: str,
    decided_at: str,
) -> DepartureGateResolutionLog:
    root = _require_workspace_root(workspace_root)
    project = _load_project(root)
    if project.get("project_id") != gate.project_id:
        raise ValueError("workspace project_id does not match departure gate")
    finding = _find_finding(gate, finding_id)
    record = build_departure_gate_resolution_record(
        gate,
        finding,
        action=action,
        reason=reason,
        reviewer_alias=reviewer_alias,
        decided_at=decided_at,
    )
    log_path = root / DEFAULT_DEPARTURE_GATE_RESOLUTION_LOG_REF
    _require_workspace_relative_path(log_path, root, "departure_gate_resolution_log")
    log = _load_or_create_log(log_path, gate)
    rebuilt = rebuild_departure_gate_resolution_log(log, [*log.records, record])
    _replace_json(log_path, rebuilt.to_json())
    return rebuilt


def rebuild_departure_gate_resolution_log(
    log: DepartureGateResolutionLog,
    records: list[DepartureGateResolutionRecord]
    | tuple[DepartureGateResolutionRecord, ...],
) -> DepartureGateResolutionLog:
    rebuilt_records = tuple(records)
    _reject_duplicate_finding_ids(rebuilt_records)
    _reject_duplicate_resolution_ids(rebuilt_records)
    counts = Counter(record.action for record in rebuilt_records)
    return DepartureGateResolutionLog(
        log_id=log.log_id,
        project_id=log.project_id,
        source_departure_gate_manifest_id=log.source_departure_gate_manifest_id,
        records=rebuilt_records,
        counts=DepartureGateResolutionCounts(
            resolution_count=len(rebuilt_records),
            warning_override_count=counts[DepartureGateResolutionAction.WARNING_OVERRIDE],
            resolved_by_review_count=counts[
                DepartureGateResolutionAction.RESOLVED_BY_REVIEW
            ],
        ),
        boundary=log.boundary,
        notes=log.notes,
    )


def load_departure_gate_resolution_log(
    path: Path | str,
) -> DepartureGateResolutionLog:
    return DepartureGateResolutionLog.model_validate_json(
        Path(path).read_text(encoding="utf-8")
    )


def _load_or_create_log(
    path: Path,
    gate: PreTripDepartureGateManifest,
) -> DepartureGateResolutionLog:
    if path.exists():
        log = load_departure_gate_resolution_log(path)
        if log.project_id != gate.project_id:
            raise ValueError("departure gate resolution log project_id does not match workspace")
        if log.source_departure_gate_manifest_id != gate.manifest_id:
            raise ValueError(
                "departure gate resolution log source manifest does not match gate"
            )
        return log
    return DepartureGateResolutionLog(
        log_id=f"departure_gate_resolution_log.{gate.project_id}.v0",
        project_id=gate.project_id,
        source_departure_gate_manifest_id=gate.manifest_id,
        counts=DepartureGateResolutionCounts(
            resolution_count=0,
            warning_override_count=0,
            resolved_by_review_count=0,
        ),
        boundary=DepartureGateResolutionBoundary(
            notes=(
                "Resolution records are append-only and workspace-only.",
                "Repo fixtures, packages, MissionGraph, runtime, and Brain state are not mutated.",
            )
        ),
    )


def _validate_log_matches_gate(
    gate: PreTripDepartureGateManifest,
    log: DepartureGateResolutionLog,
) -> None:
    if log.project_id != gate.project_id:
        raise ValueError("resolution log project_id does not match departure gate")
    if log.source_departure_gate_manifest_id != gate.manifest_id:
        raise ValueError("resolution log source manifest does not match departure gate")


def _find_finding(
    gate: PreTripDepartureGateManifest,
    finding_id: str,
) -> DepartureGateFinding:
    for finding in gate.findings:
        if finding.finding_id == finding_id:
            return finding
    raise ValueError(f"unknown departure gate finding_id: {finding_id}")


def _status_for(findings: list[DepartureGateFinding]) -> DepartureGateStatus:
    if any(finding.severity == DepartureGateSeverity.BLOCKER for finding in findings):
        return DepartureGateStatus.BLOCKED
    if any(finding.severity == DepartureGateSeverity.WARNING for finding in findings):
        return DepartureGateStatus.HOLD
    return DepartureGateStatus.PASSED


def _default_warning_resolution_reason(finding: DepartureGateFinding) -> str:
    return (
        "Admin reviewed this departure warning and accepts it for this departure "
        f"gate: {finding.rule_id}."
    )


def _require_workspace_root(workspace_root: Path | str) -> Path:
    root = Path(workspace_root)
    if not (root / "project.json").is_file():
        raise FileNotFoundError(f"workspace project.json missing under {root}")
    resolved = root.resolve()
    parts = resolved.parts
    if "tests" in parts and "fixtures" in parts and "pretrip" in parts:
        raise ValueError("departure gate resolutions must be written to a copied workspace")
    return root


def _load_project(root: Path) -> dict[str, Any]:
    return json.loads((root / "project.json").read_text(encoding="utf-8"))


def _require_workspace_relative_path(path: Path, root: Path, field: str) -> None:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"{field} must stay inside workspace root") from exc


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


def _reject_duplicate_resolution_ids(
    records: tuple[DepartureGateResolutionRecord, ...],
) -> None:
    seen_ids: set[str] = set()
    for record in records:
        if record.resolution_id in seen_ids:
            raise ValueError(f"duplicate resolution_id: {record.resolution_id}")
        seen_ids.add(record.resolution_id)


def _reject_duplicate_finding_ids(
    records: tuple[DepartureGateResolutionRecord, ...],
) -> None:
    seen_ids: set[str] = set()
    for record in records:
        if record.finding_id in seen_ids:
            raise ValueError(f"duplicate finding_id: {record.finding_id}")
        seen_ids.add(record.finding_id)


def _ref_slug(value: str) -> str:
    return (
        value.replace("/", "_")
        .replace(" ", "_")
        .replace(":", "_")
        .replace(".", "_")
    )


def _assert_no_runtime_or_raw_payload_fragments(value: Any) -> None:
    for text in _walk_strings(value):
        lowered = text.lower()
        if any(fragment in lowered for fragment in _FORBIDDEN_LOWERCASE_FRAGMENTS):
            raise ValueError("forbidden departure gate resolution fragment")


def _walk_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        strings: list[str] = []
        for item in value.values():
            strings.extend(_walk_strings(item))
        return strings
    if isinstance(value, list | tuple | set):
        strings: list[str] = []
        for item in value:
            strings.extend(_walk_strings(item))
        return strings
    return []


_FORBIDDEN_LOWERCASE_FRAGMENTS = (
    "/safety",
    "phase1incidentbridge",
    "phase1 incident bridge",
    "scout_phase2_incident_bridge",
    "<gpx",
    "<trk",
    "<trkpt",
    "<wpt",
    "<?xml",
    '"coordinates"',
    "'coordinates'",
    "catographydata",
    "pdrsample",
    ".gpx",
    ".jpg",
    ".jpeg",
    ".tif",
    ".tiff",
    "raw_payload",
    "raw_samples",
)
