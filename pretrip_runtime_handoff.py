from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from pretrip_departure_gate import DepartureGateStatus, PreTripDepartureGateManifest
from pretrip_final_mission_graph import FinalMissionGraphArtifact


SHA256_PATTERN = r"^[a-f0-9]{64}$"
DEFAULT_RUNTIME_HANDOFF_MANIFEST_REF = "outputs/runtime_handoff_manifest.json"


class StrictRuntimeHandoffModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RuntimeArtifactVersion(StrictRuntimeHandoffModel):
    version: str = Field(min_length=1)
    sha256: str = Field(pattern=SHA256_PATTERN)


class RuntimeWarningRef(StrictRuntimeHandoffModel):
    warning_id: str = Field(min_length=1)
    severity: Literal["info", "warning", "blocker"]
    summary: str = Field(min_length=1)
    runtime_eligible: bool = False


class OverrideReason(StrictRuntimeHandoffModel):
    override_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    approved_by: str = Field(min_length=1)
    approved_at: str = Field(min_length=1)


class HandoffTarget(StrictRuntimeHandoffModel):
    target_id: str = Field(min_length=1)
    target_kind: Literal["field_device", "local_runtime_node", "runtime_export"]
    target_profile: str = Field(min_length=1)


class RollbackReference(StrictRuntimeHandoffModel):
    rollback_id: str = Field(min_length=1)
    previous_handoff_id: str | None = None
    previous_mission_graph_version: str | None = None
    rollback_policy: str = Field(min_length=1)


class DepartureApprovalRecord(StrictRuntimeHandoffModel):
    approval_id: str = Field(min_length=1)
    status: Literal["pass"]
    profile_id: str = Field(min_length=1)
    approved_by: str = Field(min_length=1)
    approved_at: str = Field(min_length=1)
    package: RuntimeArtifactVersion
    unresolved_warnings: list[RuntimeWarningRef] = Field(default_factory=list)
    override_reasons: list[OverrideReason] = Field(default_factory=list)
    final_mission_graph_allowed: Literal[True] = True

    @model_validator(mode="after")
    def enforce_departure_approval_boundary(self) -> "DepartureApprovalRecord":
        _assert_no_forbidden_runtime_fragments(self.model_dump(mode="json"))
        return self


class RuntimeHandoffBoundary(StrictRuntimeHandoffModel):
    metadata_only: Literal[True] = True
    planning_workspace_dependency_allowed: Literal[False] = False
    phase1_safety_call_allowed: Literal[False] = False
    live_runtime_mutation_allowed: Literal[False] = False
    raw_payloads_embedded: Literal[False] = False
    phase1_bridge_dependency_allowed: Literal[False] = False


class RuntimeHandoffManifest(StrictRuntimeHandoffModel):
    handoff_id: str = Field(min_length=1)
    artifact_kind: Literal["runtime_handoff_manifest"] = "runtime_handoff_manifest"
    profile_id: str = Field(min_length=1)
    package: RuntimeArtifactVersion
    mission_graph: RuntimeArtifactVersion
    departure_approval_id: str = Field(min_length=1)
    approved_by: str = Field(min_length=1)
    approved_at: str = Field(min_length=1)
    handoff_target: HandoffTarget
    unresolved_warnings: list[RuntimeWarningRef] = Field(default_factory=list)
    override_reasons: list[OverrideReason] = Field(default_factory=list)
    rollback_reference: RollbackReference
    boundary: RuntimeHandoffBoundary = Field(default_factory=RuntimeHandoffBoundary)

    @field_validator("handoff_id")
    @classmethod
    def handoff_id_must_not_be_safety_path(cls, value: str) -> str:
        _assert_no_forbidden_runtime_fragments(value)
        return value

    @model_validator(mode="after")
    def enforce_metadata_only_boundary(self) -> "RuntimeHandoffManifest":
        _assert_no_forbidden_runtime_fragments(self.model_dump(mode="json"))
        return self

    def to_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n"


def build_runtime_handoff_manifest(
    *,
    handoff_id: str,
    departure_approval: DepartureApprovalRecord | dict[str, Any],
    mission_graph: RuntimeArtifactVersion | dict[str, Any],
    handoff_target: HandoffTarget | dict[str, Any],
    rollback_reference: RollbackReference | dict[str, Any],
) -> RuntimeHandoffManifest:
    approval = DepartureApprovalRecord.model_validate(departure_approval)
    mission_graph_version = RuntimeArtifactVersion.model_validate(mission_graph)
    target = HandoffTarget.model_validate(handoff_target)
    rollback = RollbackReference.model_validate(rollback_reference)

    return RuntimeHandoffManifest(
        handoff_id=handoff_id,
        profile_id=approval.profile_id,
        package=approval.package,
        mission_graph=mission_graph_version,
        departure_approval_id=approval.approval_id,
        approved_by=approval.approved_by,
        approved_at=approval.approved_at,
        handoff_target=target,
        unresolved_warnings=approval.unresolved_warnings,
        override_reasons=approval.override_reasons,
        rollback_reference=rollback,
    )


def build_runtime_handoff_manifest_from_final_graph(
    departure_gate: PreTripDepartureGateManifest | dict[str, Any],
    final_mission_graph: FinalMissionGraphArtifact | dict[str, Any],
    *,
    handoff_id: str,
    approved_by: str,
    approved_at: str,
    handoff_target: HandoffTarget | dict[str, Any],
    rollback_reference: RollbackReference | dict[str, Any],
) -> RuntimeHandoffManifest:
    gate = PreTripDepartureGateManifest.model_validate(departure_gate)
    final_graph = FinalMissionGraphArtifact.model_validate(final_mission_graph)
    _require_passed_departure_gate(gate)
    _require_final_graph_matches_gate(gate, final_graph)

    target = HandoffTarget.model_validate(handoff_target)
    rollback = RollbackReference.model_validate(rollback_reference)
    return RuntimeHandoffManifest(
        handoff_id=handoff_id,
        profile_id=final_graph.profile_id,
        package=RuntimeArtifactVersion(
            version=_package_version(final_graph),
            sha256=final_graph.source_package_ref.sha256,
        ),
        mission_graph=RuntimeArtifactVersion(
            version=final_graph.mission_graph_version,
            sha256=final_graph.final_mission_graph_sha256,
        ),
        departure_approval_id=final_graph.departure_approval_id,
        approved_by=approved_by,
        approved_at=approved_at,
        handoff_target=target,
        unresolved_warnings=[],
        override_reasons=_override_reasons_from_gate(gate),
        rollback_reference=rollback,
    )


def write_runtime_handoff_manifest_for_workspace(
    workspace_root: Path | str,
    departure_gate: PreTripDepartureGateManifest | dict[str, Any],
    final_mission_graph: FinalMissionGraphArtifact | dict[str, Any],
    *,
    handoff_id: str,
    approved_by: str,
    approved_at: str,
    handoff_target: HandoffTarget | dict[str, Any],
    rollback_reference: RollbackReference | dict[str, Any],
    output_ref: str = DEFAULT_RUNTIME_HANDOFF_MANIFEST_REF,
) -> RuntimeHandoffManifest:
    root = _require_workspace_root(workspace_root)
    output_path = root / output_ref
    _require_workspace_relative_path(output_path, root, "runtime_handoff_manifest")
    if output_path.exists():
        raise FileExistsError(f"runtime handoff manifest already exists: {output_path}")
    manifest = build_runtime_handoff_manifest_from_final_graph(
        departure_gate,
        final_mission_graph,
        handoff_id=handoff_id,
        approved_by=approved_by,
        approved_at=approved_at,
        handoff_target=handoff_target,
        rollback_reference=rollback_reference,
    )
    _replace_json(output_path, manifest.to_json())
    return manifest


def load_runtime_handoff_manifest(path: Path | str) -> RuntimeHandoffManifest:
    return RuntimeHandoffManifest.model_validate_json(
        Path(path).read_text(encoding="utf-8")
    )


def _require_passed_departure_gate(gate: PreTripDepartureGateManifest) -> None:
    if gate.status != DepartureGateStatus.PASSED:
        raise ValueError("runtime handoff requires passed departure gate")
    if not gate.approval.approval_granted:
        raise ValueError("runtime handoff requires departure approval")
    if not gate.approval.final_mission_graph_generation_allowed:
        raise ValueError("runtime handoff requires final MissionGraph approval")
    if gate.approval.blockers:
        raise ValueError("runtime handoff rejects approval blockers")
    if gate.approval.unresolved_warnings:
        raise ValueError("runtime handoff rejects unresolved warnings")
    if not gate.approval.approved_by or not gate.approval.approved_at:
        raise ValueError("runtime handoff requires departure approver and approval time")


def _require_final_graph_matches_gate(
    gate: PreTripDepartureGateManifest,
    final_graph: FinalMissionGraphArtifact,
) -> None:
    if final_graph.project_id != gate.project_id:
        raise ValueError("final MissionGraph project_id does not match departure gate")
    if final_graph.profile_id != gate.approval.profile_id:
        raise ValueError("final MissionGraph profile_id does not match departure gate")
    if final_graph.departure_approval_id != gate.approval.approval_id:
        raise ValueError("final MissionGraph departure approval does not match gate")
    if final_graph.approved_by != gate.approval.approved_by:
        raise ValueError("final MissionGraph departure approver does not match gate")
    if final_graph.approved_at != gate.approval.approved_at:
        raise ValueError("final MissionGraph departure approval time does not match gate")
    if final_graph.source_package_ref.ref != gate.approval.reviewed_package_ref:
        raise ValueError("final MissionGraph package ref does not match gate")
    if final_graph.source_package_ref.sha256 != gate.approval.reviewed_package_hash:
        raise ValueError("final MissionGraph package hash does not match gate")
    if (
        final_graph.source_mission_graph_ref.ref
        != gate.approval.mission_graph_candidate_ref
    ):
        raise ValueError("final MissionGraph source graph ref does not match gate")
    if (
        final_graph.source_mission_graph_ref.sha256
        != gate.approval.mission_graph_candidate_hash
    ):
        raise ValueError("final MissionGraph source graph hash does not match gate")


def _package_version(final_graph: FinalMissionGraphArtifact) -> str:
    package_id = final_graph.source_package_ref.summary.get("package_id")
    package_version = final_graph.source_package_ref.summary.get("version")
    if package_id and package_version:
        return f"{package_id}:{package_version}"
    return final_graph.source_package_ref.ref


def _override_reasons_from_gate(
    gate: PreTripDepartureGateManifest,
) -> list[OverrideReason]:
    return [
        OverrideReason(
            override_id=f"departure_gate_override.{gate.project_id}.{index + 1:02d}",
            reason=reason,
            approved_by=gate.approval.approved_by or "unknown",
            approved_at=gate.approval.approved_at or "unknown",
        )
        for index, reason in enumerate(gate.approval.override_reasons)
    ]


def _require_workspace_root(workspace_root: Path | str) -> Path:
    root = Path(workspace_root)
    if not (root / "project.json").is_file():
        raise FileNotFoundError(f"workspace project.json missing under {root}")
    resolved = root.resolve()
    parts = resolved.parts
    if "tests" in parts and "fixtures" in parts and "pretrip" in parts:
        raise ValueError("runtime handoff manifest must be written to a copied workspace")
    return root


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


def _assert_no_forbidden_runtime_fragments(value: Any) -> None:
    for text in _walk_strings(value):
        lowered = text.lower()
        if any(fragment in lowered for fragment in _FORBIDDEN_LOWERCASE_FRAGMENTS):
            raise ValueError("forbidden runtime/raw payload fragment")


def _walk_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        strings: list[str] = []
        for item in value.values():
            strings.extend(_walk_strings(item))
        return strings
    if isinstance(value, list | tuple | set):
        strings = []
        for item in value:
            strings.extend(_walk_strings(item))
        return strings
    return []


_FORBIDDEN_LOWERCASE_FRAGMENTS = (
    "/safety",
    "phase1incidentbridge",
    "phase1 incident bridge",
    "phase1_bridge",
    "phase1-bridge",
    "phase1_incident_bridge",
    "scout_phase2_incident_bridge",
    "<gpx",
    "<trk",
    "<trkpt",
    "<rte",
    "<wpt",
    "<?xml",
    '"coordinates"',
    "'coordinates'",
)
