from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from mission_models import MissionGraph
from pretrip_departure_gate import DepartureGateStatus, PreTripDepartureGateManifest


DEFAULT_CHILAI_PROJECT_REF = (
    "tests/fixtures/pretrip/projects/chilai_nanhua_day1/project.json"
)
DEFAULT_FINAL_MISSION_GRAPH_REF = "outputs/final_mission_graph.json"


class StrictFinalMissionGraphModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FinalMissionGraphRef(StrictFinalMissionGraphModel):
    ref_key: str
    ref: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    exists: Literal[True] = True
    summary: dict[str, Any] = Field(default_factory=dict)


class FinalMissionGraphCounts(StrictFinalMissionGraphModel):
    checkpoint_count: int = Field(ge=0)
    segment_count: int = Field(ge=0)
    diversion_point_count: int = Field(ge=0)
    unresolved_warning_count: Literal[0] = 0
    blocker_count: Literal[0] = 0
    runtime_write_count: Literal[0] = 0
    safety_call_count: Literal[0] = 0
    phase2_writeback_count: Literal[0] = 0


class FinalMissionGraphBoundary(StrictFinalMissionGraphModel):
    immutable: Literal[True] = True
    generated_after_departure_gate_passed: Literal[True] = True
    planning_workspace_dependency_allowed: Literal[False] = False
    runtime_handoff_required: Literal[True] = True
    runtime_handoff_performed: Literal[False] = False
    phase1_runtime_mutation_allowed: Literal[False] = False
    safety_api_calls_allowed: Literal[False] = False
    phase2_writeback_allowed: Literal[False] = False
    external_api_calls_made: Literal[False] = False
    raw_payloads_embedded: Literal[False] = False
    notes: list[str] = Field(
        default_factory=lambda: [
            "Final MissionGraph / 最終任務圖 is generated only after Departure Gate passes.",
            "This artifact is not Runtime Handoff / 現場 runtime 交接 approval.",
            "No Phase 1 runtime state is mutated by this builder.",
        ]
    )


class FinalMissionGraphArtifact(StrictFinalMissionGraphModel):
    artifact_id: str
    artifact_kind: Literal["pretrip_final_mission_graph"] = (
        "pretrip_final_mission_graph"
    )
    project_id: str
    status: Literal["finalized"] = "finalized"
    profile_id: str
    mission_graph_version: str
    final_mission_graph_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    departure_approval_id: str
    approved_by: str
    approved_at: str
    source_package_ref: FinalMissionGraphRef
    source_mission_graph_ref: FinalMissionGraphRef
    mission_graph: MissionGraph
    counts: FinalMissionGraphCounts
    boundary: FinalMissionGraphBoundary = Field(default_factory=FinalMissionGraphBoundary)
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_final_graph_boundary(self) -> "FinalMissionGraphArtifact":
        if self.mission_graph.mission_id != self.mission_graph_version:
            raise ValueError("mission_graph_version must match MissionGraph mission_id")
        _assert_no_runtime_or_raw_payload_fragments(self.model_dump(mode="json"))
        graph_hash = _sha256_json(self.mission_graph.model_dump(mode="json"))
        if self.final_mission_graph_sha256 != graph_hash:
            raise ValueError("final_mission_graph_sha256 must match mission_graph")
        if self.counts.checkpoint_count != len(self.mission_graph.checkpoints):
            raise ValueError("checkpoint_count must match mission_graph")
        if self.counts.segment_count != len(self.mission_graph.segments):
            raise ValueError("segment_count must match mission_graph")
        if self.counts.diversion_point_count != len(self.mission_graph.diversion_points):
            raise ValueError("diversion_point_count must match mission_graph")
        return self

    def to_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n"


def build_chilai_final_mission_graph_artifact(
    project_root: Path | str,
    departure_gate: PreTripDepartureGateManifest | dict[str, Any],
) -> FinalMissionGraphArtifact:
    gate = PreTripDepartureGateManifest.model_validate(departure_gate)
    _require_passed_departure_gate(gate)

    project_path = _resolve_chilai_project_path(Path(project_root))
    fixture_root = project_path.parent
    project = _load_json(project_path)
    reviewed_package_ref = project["reviewed_package_ref"]
    reviewed_graph_ref = project["compiled_mission_graph_reviewed_ref"]
    package_path = fixture_root / reviewed_package_ref
    graph_path = fixture_root / reviewed_graph_ref
    package = _load_json(package_path)
    source_graph = MissionGraph.model_validate(_load_json(graph_path))

    package_sha = _sha256_file(package_path)
    graph_sha = _sha256_file(graph_path)
    if gate.approval.reviewed_package_ref != reviewed_package_ref:
        raise ValueError("departure gate reviewed package ref does not match project")
    if gate.approval.reviewed_package_hash != package_sha:
        raise ValueError("departure gate reviewed package hash does not match project")
    if gate.approval.mission_graph_candidate_ref != reviewed_graph_ref:
        raise ValueError("departure gate reviewed MissionGraph ref does not match project")
    if gate.approval.mission_graph_candidate_hash != graph_sha:
        raise ValueError("departure gate reviewed MissionGraph hash does not match project")

    mission_graph_version = (
        f"{source_graph.mission_id}.final.{gate.approval.profile_id}"
    )
    final_graph = _finalize_mission_graph(
        source_graph,
        mission_graph_version=mission_graph_version,
        source_artifact_id=package["route_summary"]["artifact_id"],
    )
    final_hash = _sha256_json(final_graph.model_dump(mode="json"))

    return FinalMissionGraphArtifact(
        artifact_id=f"final_mission_graph.{gate.project_id}.{gate.approval.profile_id}",
        project_id=gate.project_id,
        profile_id=gate.approval.profile_id,
        mission_graph_version=mission_graph_version,
        final_mission_graph_sha256=final_hash,
        departure_approval_id=gate.approval.approval_id,
        approved_by=gate.approval.approved_by or "",
        approved_at=gate.approval.approved_at or "",
        source_package_ref=FinalMissionGraphRef(
            ref_key="reviewed_package_ref",
            ref=reviewed_package_ref,
            sha256=package_sha,
            summary={
                "package_id": package.get("package_id"),
                "version": package.get("version"),
                "status": package.get("status"),
            },
        ),
        source_mission_graph_ref=FinalMissionGraphRef(
            ref_key="compiled_mission_graph_reviewed_ref",
            ref=reviewed_graph_ref,
            sha256=graph_sha,
            summary={
                "mission_id": source_graph.mission_id,
                "checkpoint_count": len(source_graph.checkpoints),
                "segment_count": len(source_graph.segments),
                "diversion_point_count": len(source_graph.diversion_points),
            },
        ),
        mission_graph=final_graph,
        counts=FinalMissionGraphCounts(
            checkpoint_count=len(final_graph.checkpoints),
            segment_count=len(final_graph.segments),
            diversion_point_count=len(final_graph.diversion_points),
        ),
        notes=[
            "Generated from reviewed MissionGraph after explicit Departure Gate approval.",
            "Route source refs are sanitized to artifact tokens so the final graph does not point at local raw GPX paths.",
        ],
    )


def write_final_mission_graph_artifact(
    workspace_root: Path | str,
    departure_gate: PreTripDepartureGateManifest | dict[str, Any],
    *,
    output_ref: str = DEFAULT_FINAL_MISSION_GRAPH_REF,
) -> FinalMissionGraphArtifact:
    root = _require_workspace_root(workspace_root)
    output_path = root / output_ref
    _require_workspace_relative_path(output_path, root, "final_mission_graph")
    if output_path.exists():
        raise FileExistsError(f"final MissionGraph already exists: {output_path}")
    artifact = build_chilai_final_mission_graph_artifact(root, departure_gate)
    _replace_json(output_path, artifact.to_json())
    return artifact


def load_final_mission_graph_artifact(path: Path | str) -> FinalMissionGraphArtifact:
    return FinalMissionGraphArtifact.model_validate_json(
        Path(path).read_text(encoding="utf-8")
    )


def _require_passed_departure_gate(gate: PreTripDepartureGateManifest) -> None:
    if gate.status != DepartureGateStatus.PASSED:
        raise ValueError("final MissionGraph generation requires passed departure gate")
    if not gate.approval.approval_granted:
        raise ValueError("final MissionGraph generation requires departure approval")
    if not gate.approval.final_mission_graph_generation_allowed:
        raise ValueError("final MissionGraph generation is not allowed by approval")
    if gate.approval.blockers:
        raise ValueError("final MissionGraph generation rejects approval blockers")
    if gate.approval.unresolved_warnings:
        raise ValueError("final MissionGraph generation rejects unresolved warnings")
    if not gate.approval.approved_by or not gate.approval.approved_at:
        raise ValueError("final MissionGraph generation requires approver and approval time")


def _finalize_mission_graph(
    source_graph: MissionGraph,
    *,
    mission_graph_version: str,
    source_artifact_id: str,
) -> MissionGraph:
    payload = source_graph.model_dump(mode="json")
    safe_artifact_ref = _sanitize_source_ref(source_artifact_id)
    payload["mission_id"] = mission_graph_version
    payload["route_source"] = safe_artifact_ref
    for checkpoint in payload.get("checkpoints", []):
        checkpoint["source"] = _sanitize_source_ref(checkpoint.get("source"))
    return MissionGraph.model_validate(payload)


def _resolve_chilai_project_path(path: Path) -> Path:
    if path.name == "project.json":
        return path
    if (path / "project.json").exists():
        return path / "project.json"
    repo_fixture = path / DEFAULT_CHILAI_PROJECT_REF
    if repo_fixture.exists():
        return repo_fixture
    raise FileNotFoundError(f"could not find Chilai pretrip project.json under {path}")


def _require_workspace_root(workspace_root: Path | str) -> Path:
    root = Path(workspace_root)
    if not (root / "project.json").is_file():
        raise FileNotFoundError(f"workspace project.json missing under {root}")
    resolved = root.resolve()
    parts = resolved.parts
    if "tests" in parts and "fixtures" in parts and "pretrip" in parts:
        raise ValueError("final MissionGraph must be written to a copied workspace")
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


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256_json(payload: Any) -> str:
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def _sanitize_source_ref(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    lowered = value.lower()
    if ".gpx" in lowered or "/users/" in lowered:
        return "artifact:gpx:chilai_nanhua_day1"
    return value.replace("artifact.gpx.", "artifact:gpx:").replace(
        "artifact.photo.",
        "artifact:photo:",
    )


def _assert_no_runtime_or_raw_payload_fragments(payload: Any) -> None:
    for text in _walk_strings(payload):
        lowered = text.lower()
        if any(fragment in lowered for fragment in _FORBIDDEN_LOWERCASE_FRAGMENTS):
            raise ValueError("forbidden final MissionGraph fragment")


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
    "catographydata",
    "pdrsample",
    "/users/",
    ".gpx",
    ".jpg",
    ".jpeg",
    ".tif",
    ".tiff",
    "raw_payload",
    "raw_samples",
)
