from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from pretrip_final_mission_graph import FinalMissionGraphArtifact
from pretrip_runtime_export import RuntimeExportBundleManifest
from pretrip_runtime_handoff import HandoffTarget
from runtime_artifact_resolution import (
    DEFAULT_RUNTIME_ARTIFACT_RESOLUTION_MANIFEST_NAME,
    SYMBOLIC_ARTIFACT_PREFIX,
    resolve_runtime_route_source,
)

SHA256_PATTERN = r"^[a-f0-9]{64}$"


class StrictRuntimeArtifactResolutionModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RuntimeArtifactResolutionRef(StrictRuntimeArtifactResolutionModel):
    artifact_ref: str = Field(min_length=1)
    artifact_kind: Literal["gpx_route"] = "gpx_route"
    runtime_ref: str = Field(min_length=1)
    runtime_path_basis: Literal["relative_to_resolution_manifest"] = (
        "relative_to_resolution_manifest"
    )
    sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    required: Literal[True] = True
    resolved: bool = False

    @field_validator("artifact_ref")
    @classmethod
    def artifact_ref_must_be_symbolic(cls, value: str) -> str:
        if not value.startswith(SYMBOLIC_ARTIFACT_PREFIX):
            raise ValueError("artifact_ref must be a symbolic artifact reference")
        _assert_no_forbidden_runtime_artifact_fragments(value)
        return value

    @field_validator("runtime_ref")
    @classmethod
    def runtime_ref_must_be_relative_and_metadata_only(cls, value: str) -> str:
        _assert_relative_runtime_ref(value)
        _assert_no_forbidden_runtime_artifact_fragments(value)
        return value


class RuntimeArtifactResolutionCounts(StrictRuntimeArtifactResolutionModel):
    artifact_resolution_count: int = Field(ge=0)
    required_resolution_count: int = Field(ge=0)
    resolved_count: int = Field(ge=0)
    missing_count: int = Field(ge=0)
    raw_payload_copy_count: Literal[0] = 0
    safety_api_call_count: Literal[0] = 0
    phase1_live_session_mutation_count: Literal[0] = 0
    phase2_writeback_count: Literal[0] = 0


class RuntimeArtifactResolutionBoundary(StrictRuntimeArtifactResolutionModel):
    metadata_only: Literal[True] = True
    raw_payloads_embedded: Literal[False] = False
    route_payload_copy_allowed: Literal[False] = False
    planning_workspace_dependency_allowed: Literal[False] = False
    live_runtime_activation_allowed: Literal[False] = False
    phase1_live_session_mutation_allowed: Literal[False] = False
    safety_api_calls_allowed: Literal[False] = False
    phase2_writeback_allowed: Literal[False] = False
    missing_required_artifact_blocks_activation: Literal[True] = True
    route_source_policy: Literal[
        "symbolic_artifact_ref_resolved_by_runtime_target"
    ] = "symbolic_artifact_ref_resolved_by_runtime_target"
    notes: list[str] = Field(
        default_factory=lambda: [
            "Runtime Artifact Resolution / runtime artifact 解析 keeps the MissionGraph route_source symbolic.",
            "The runtime target must mount or provide the referenced route file before activation.",
            "This manifest records metadata only and does not copy raw route payloads.",
        ]
    )


class RuntimeArtifactResolutionManifest(StrictRuntimeArtifactResolutionModel):
    manifest_id: str = Field(min_length=1)
    artifact_kind: Literal["runtime_artifact_resolution_manifest"] = (
        "runtime_artifact_resolution_manifest"
    )
    project_id: str = Field(min_length=1)
    export_id: str = Field(min_length=1)
    runtime_target: HandoffTarget
    mission_graph_version: str = Field(min_length=1)
    mission_graph_sha256: str = Field(pattern=SHA256_PATTERN)
    route_source_ref: str = Field(min_length=1)
    resolutions: list[RuntimeArtifactResolutionRef] = Field(min_length=1)
    counts: RuntimeArtifactResolutionCounts
    boundary: RuntimeArtifactResolutionBoundary = Field(
        default_factory=RuntimeArtifactResolutionBoundary
    )
    notes: list[str] = Field(default_factory=list)

    @field_validator("route_source_ref")
    @classmethod
    def route_source_ref_must_be_symbolic(cls, value: str) -> str:
        if not value.startswith(SYMBOLIC_ARTIFACT_PREFIX):
            raise ValueError("route_source_ref must be a symbolic artifact reference")
        _assert_no_forbidden_runtime_artifact_fragments(value)
        return value

    @model_validator(mode="after")
    def enforce_resolution_contract(self) -> "RuntimeArtifactResolutionManifest":
        _assert_no_forbidden_runtime_artifact_fragments(self.model_dump(mode="json"))
        route_matches = [
            resolution
            for resolution in self.resolutions
            if resolution.artifact_ref == self.route_source_ref
        ]
        if len(route_matches) != 1:
            raise ValueError("route_source_ref must have exactly one resolution")

        expected_counts = _counts_for_resolutions(self.resolutions)
        if self.counts != expected_counts:
            raise ValueError("counts must match runtime artifact resolutions")
        return self

    def to_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n"


def build_runtime_artifact_resolution_manifest(
    runtime_export: RuntimeExportBundleManifest | dict[str, Any],
    final_mission_graph: FinalMissionGraphArtifact | dict[str, Any],
    *,
    runtime_ref: str,
    sha256: str | None = None,
    resolved: bool = False,
) -> RuntimeArtifactResolutionManifest:
    export = RuntimeExportBundleManifest.model_validate(runtime_export)
    final_graph = FinalMissionGraphArtifact.model_validate(final_mission_graph)
    _require_export_matches_final_graph(export, final_graph)

    route_source_ref = final_graph.mission_graph.route_source
    resolution = RuntimeArtifactResolutionRef(
        artifact_ref=route_source_ref,
        runtime_ref=runtime_ref,
        sha256=sha256,
        resolved=resolved,
    )
    resolutions = [resolution]
    return RuntimeArtifactResolutionManifest(
        manifest_id=f"runtime_artifact_resolution.{export.export_id}",
        project_id=export.project_id,
        export_id=export.export_id,
        runtime_target=export.runtime_target,
        mission_graph_version=final_graph.mission_graph_version,
        mission_graph_sha256=final_graph.final_mission_graph_sha256,
        route_source_ref=route_source_ref,
        resolutions=resolutions,
        counts=_counts_for_resolutions(resolutions),
        notes=[
            "Route artifact refs remain symbolic in the MissionGraph.",
            "This resolver manifest binds the symbolic ref to a runtime-target relative mount path.",
        ],
    )


def write_runtime_artifact_resolution_manifest_for_workspace(
    workspace_root: Path | str,
    runtime_export: RuntimeExportBundleManifest | dict[str, Any],
    final_mission_graph: FinalMissionGraphArtifact | dict[str, Any],
    *,
    runtime_ref: str,
    sha256: str | None = None,
    resolved: bool = False,
) -> RuntimeArtifactResolutionManifest:
    root = _require_workspace_root(workspace_root)
    export = RuntimeExportBundleManifest.model_validate(runtime_export)
    final_graph = FinalMissionGraphArtifact.model_validate(final_mission_graph)
    manifest = build_runtime_artifact_resolution_manifest(
        export,
        final_graph,
        runtime_ref=runtime_ref,
        sha256=sha256,
        resolved=resolved,
    )
    export_root = root / "runtime_exports" / export.export_id
    _require_workspace_relative_path(export_root, root, "runtime_artifact_resolution")
    if not export_root.is_dir():
        raise FileNotFoundError(f"runtime export bundle missing: {export_root}")

    manifest_path = export_root / DEFAULT_RUNTIME_ARTIFACT_RESOLUTION_MANIFEST_NAME
    _require_workspace_relative_path(manifest_path, root, "runtime_artifact_resolution")
    if manifest_path.exists():
        raise FileExistsError(
            f"runtime artifact resolution manifest already exists: {manifest_path}"
        )
    _replace_json(manifest_path, manifest.to_json())
    return manifest


def load_runtime_artifact_resolution_manifest(
    path: Path | str,
) -> RuntimeArtifactResolutionManifest:
    return RuntimeArtifactResolutionManifest.model_validate_json(
        Path(path).read_text(encoding="utf-8")
    )


def _require_export_matches_final_graph(
    runtime_export: RuntimeExportBundleManifest,
    final_mission_graph: FinalMissionGraphArtifact,
) -> None:
    if runtime_export.project_id != final_mission_graph.project_id:
        raise ValueError("runtime export project_id does not match final MissionGraph")
    if runtime_export.profile_id != final_mission_graph.profile_id:
        raise ValueError("runtime export profile does not match final MissionGraph")
    if runtime_export.departure_approval_id != final_mission_graph.departure_approval_id:
        raise ValueError(
            "runtime export departure approval does not match final MissionGraph"
        )
    if runtime_export.mission_graph_version != final_mission_graph.mission_graph_version:
        raise ValueError("runtime export MissionGraph version does not match final graph")
    if runtime_export.mission_graph_sha256 != final_mission_graph.final_mission_graph_sha256:
        raise ValueError("runtime export MissionGraph hash does not match final graph")


def _counts_for_resolutions(
    resolutions: list[RuntimeArtifactResolutionRef],
) -> RuntimeArtifactResolutionCounts:
    return RuntimeArtifactResolutionCounts(
        artifact_resolution_count=len(resolutions),
        required_resolution_count=sum(1 for resolution in resolutions if resolution.required),
        resolved_count=sum(1 for resolution in resolutions if resolution.resolved),
        missing_count=sum(1 for resolution in resolutions if not resolution.resolved),
    )


def _require_workspace_root(workspace_root: Path | str) -> Path:
    root = Path(workspace_root)
    if not (root / "project.json").is_file():
        raise FileNotFoundError(f"workspace project.json missing under {root}")
    resolved = root.resolve()
    parts = resolved.parts
    if "tests" in parts and "fixtures" in parts and "pretrip" in parts:
        raise ValueError(
            "runtime artifact resolution manifest must be written to a copied workspace"
        )
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


def _assert_relative_runtime_ref(value: str) -> None:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("runtime_ref must be a relative runtime artifact path")


def _assert_no_forbidden_runtime_artifact_fragments(payload: Any) -> None:
    for text in _walk_strings(payload):
        lowered = text.lower()
        if any(fragment in lowered for fragment in _FORBIDDEN_LOWERCASE_FRAGMENTS):
            raise ValueError("forbidden runtime artifact resolution fragment")


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
    "/users/",
    "catographydata",
    "pdrsample",
    "<gpx",
    "<trk",
    "<trkpt",
    "<rte",
    "<wpt",
    "<?xml",
    "data:image",
    "base64,",
    "raw_payload",
    "raw_samples",
    "incident_samples",
)
