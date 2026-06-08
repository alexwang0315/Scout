from __future__ import annotations

import hashlib
import json
import os
import tempfile
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from mission_models import MissionGraph
from pretrip_final_mission_graph import FinalMissionGraphArtifact
from pretrip_runtime_handoff import HandoffTarget, RuntimeHandoffManifest


DEFAULT_RUNTIME_EXPORT_MANIFEST_NAME = "runtime_export_manifest.json"


class RuntimeExportStatus(StrEnum):
    EXPORTED_NOT_ACTIVATED = "exported_not_activated"


class StrictRuntimeExportModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RuntimeExportFileRef(StrictRuntimeExportModel):
    ref: str
    artifact_kind: Literal["mission_graph", "runtime_handoff_manifest"]
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    write_required: Literal[True] = True


class RuntimeExportFileSet(StrictRuntimeExportModel):
    mission_graph: RuntimeExportFileRef
    runtime_handoff_manifest: RuntimeExportFileRef


class RuntimeExportCounts(StrictRuntimeExportModel):
    runtime_file_write_count: Literal[2] = 2
    live_runtime_activation_count: Literal[0] = 0
    safety_api_call_count: Literal[0] = 0
    phase1_live_session_mutation_count: Literal[0] = 0
    phase2_writeback_count: Literal[0] = 0
    raw_payload_copy_count: Literal[0] = 0


class RuntimeExportBoundary(StrictRuntimeExportModel):
    runtime_file_write_allowed: Literal[True] = True
    live_runtime_activation_allowed: Literal[False] = False
    phase1_live_session_mutation_allowed: Literal[False] = False
    safety_api_calls_allowed: Literal[False] = False
    phase2_writeback_allowed: Literal[False] = False
    planning_workspace_dependency_allowed: Literal[False] = False
    raw_payloads_embedded: Literal[False] = False
    route_source_resolution_policy: Literal[
        "runtime_target_must_resolve_artifact_refs"
    ] = "runtime_target_must_resolve_artifact_refs"
    notes: list[str] = Field(
        default_factory=lambda: [
            "Runtime Export / runtime 匯出 writes immutable runtime input files only.",
            "Activation / 啟動現場 session is a separate Phase 1 runtime decision.",
            "No live safety endpoint is called by this exporter.",
        ]
    )


class RuntimeExportBundleManifest(StrictRuntimeExportModel):
    export_id: str
    artifact_kind: Literal["pretrip_runtime_export_bundle"] = (
        "pretrip_runtime_export_bundle"
    )
    project_id: str
    status: RuntimeExportStatus = RuntimeExportStatus.EXPORTED_NOT_ACTIVATED
    profile_id: str
    departure_approval_id: str
    handoff_id: str
    mission_graph_version: str
    mission_graph_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    package_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    runtime_target: HandoffTarget
    files: RuntimeExportFileSet
    counts: RuntimeExportCounts = Field(default_factory=RuntimeExportCounts)
    boundary: RuntimeExportBoundary = Field(default_factory=RuntimeExportBoundary)
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_runtime_export_boundary(self) -> "RuntimeExportBundleManifest":
        if self.files.mission_graph.sha256 != self.mission_graph_sha256:
            raise ValueError("mission_graph file hash must match export hash")
        _assert_no_runtime_or_raw_payload_fragments(self.model_dump(mode="json"))
        return self

    def to_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n"


def build_runtime_export_bundle_manifest(
    final_mission_graph: FinalMissionGraphArtifact | dict[str, Any],
    runtime_handoff: RuntimeHandoffManifest | dict[str, Any],
    *,
    export_id: str,
) -> RuntimeExportBundleManifest:
    final_graph = FinalMissionGraphArtifact.model_validate(final_mission_graph)
    handoff = RuntimeHandoffManifest.model_validate(runtime_handoff)
    _require_handoff_matches_final_graph(final_graph, handoff)

    export_root_ref = f"runtime_exports/{export_id}"
    return RuntimeExportBundleManifest(
        export_id=export_id,
        project_id=final_graph.project_id,
        profile_id=final_graph.profile_id,
        departure_approval_id=final_graph.departure_approval_id,
        handoff_id=handoff.handoff_id,
        mission_graph_version=final_graph.mission_graph_version,
        mission_graph_sha256=final_graph.final_mission_graph_sha256,
        package_sha256=final_graph.source_package_ref.sha256,
        runtime_target=handoff.handoff_target,
        files=RuntimeExportFileSet(
            mission_graph=RuntimeExportFileRef(
                ref=f"{export_root_ref}/mission_graph.json",
                artifact_kind="mission_graph",
                sha256=final_graph.final_mission_graph_sha256,
            ),
            runtime_handoff_manifest=RuntimeExportFileRef(
                ref=f"{export_root_ref}/runtime_handoff_manifest.json",
                artifact_kind="runtime_handoff_manifest",
                sha256=_sha256_json(handoff.model_dump(mode="json")),
            ),
        ),
        notes=[
            "Phase 4 is allowed to write this immutable runtime export bundle.",
            "The exported MissionGraph remains symbolic for route source refs; the runtime target must resolve artifact refs before live activation.",
        ],
    )


def write_runtime_export_bundle_for_workspace(
    workspace_root: Path | str,
    final_mission_graph: FinalMissionGraphArtifact | dict[str, Any],
    runtime_handoff: RuntimeHandoffManifest | dict[str, Any],
    *,
    export_id: str,
) -> RuntimeExportBundleManifest:
    root = _require_workspace_root(workspace_root)
    final_graph = FinalMissionGraphArtifact.model_validate(final_mission_graph)
    handoff = RuntimeHandoffManifest.model_validate(runtime_handoff)
    manifest = build_runtime_export_bundle_manifest(
        final_graph,
        handoff,
        export_id=export_id,
    )
    export_root = root / "runtime_exports" / export_id
    if export_root.exists():
        raise FileExistsError(f"runtime export bundle already exists: {export_root}")
    _require_workspace_relative_path(export_root, root, "runtime_export_bundle")

    mission_graph_text = _json_text(final_graph.mission_graph.model_dump(mode="json"))
    handoff_text = _json_text(handoff.model_dump(mode="json"))
    if _sha256_text(mission_graph_text) != manifest.files.mission_graph.sha256:
        raise ValueError("MissionGraph hash does not match export manifest")
    if _sha256_text(handoff_text) != manifest.files.runtime_handoff_manifest.sha256:
        raise ValueError("Runtime handoff hash does not match export manifest")

    try:
        export_root.mkdir(parents=True)
        _replace_json(export_root / "mission_graph.json", mission_graph_text)
        _replace_json(export_root / "runtime_handoff_manifest.json", handoff_text)
        _replace_json(export_root / DEFAULT_RUNTIME_EXPORT_MANIFEST_NAME, manifest.to_json())
    except Exception:
        if export_root.exists():
            for path in sorted(export_root.rglob("*"), reverse=True):
                if path.is_file():
                    path.unlink()
                elif path.is_dir():
                    path.rmdir()
            export_root.rmdir()
        raise

    MissionGraph.model_validate_json((export_root / "mission_graph.json").read_text(encoding="utf-8"))
    return manifest


def load_runtime_export_bundle_manifest(
    path: Path | str,
) -> RuntimeExportBundleManifest:
    return RuntimeExportBundleManifest.model_validate_json(
        Path(path).read_text(encoding="utf-8")
    )


def _require_handoff_matches_final_graph(
    final_graph: FinalMissionGraphArtifact,
    handoff: RuntimeHandoffManifest,
) -> None:
    if handoff.departure_approval_id != final_graph.departure_approval_id:
        raise ValueError("handoff departure approval does not match final MissionGraph")
    if handoff.profile_id != final_graph.profile_id:
        raise ValueError("handoff profile does not match final MissionGraph")
    if handoff.package.sha256 != final_graph.source_package_ref.sha256:
        raise ValueError("handoff package hash does not match final MissionGraph")
    if handoff.mission_graph.version != final_graph.mission_graph_version:
        raise ValueError("handoff MissionGraph version does not match final MissionGraph")
    if handoff.mission_graph.sha256 != final_graph.final_mission_graph_sha256:
        raise ValueError("handoff MissionGraph hash does not match final MissionGraph")
    if not handoff.boundary.metadata_only:
        raise ValueError("handoff manifest must remain metadata-only before export")


def _require_workspace_root(workspace_root: Path | str) -> Path:
    root = Path(workspace_root)
    if not (root / "project.json").is_file():
        raise FileNotFoundError(f"workspace project.json missing under {root}")
    resolved = root.resolve()
    parts = resolved.parts
    if "tests" in parts and "fixtures" in parts and "pretrip" in parts:
        raise ValueError("runtime export bundle must be written to a copied workspace")
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


def _json_text(payload: Any) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _sha256_json(payload: Any) -> str:
    return _sha256_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )


def _sha256_text(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _assert_no_runtime_or_raw_payload_fragments(payload: Any) -> None:
    for text in _walk_strings(payload):
        lowered = text.lower()
        if any(fragment in lowered for fragment in _FORBIDDEN_LOWERCASE_FRAGMENTS):
            raise ValueError("forbidden runtime export fragment")


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
    '"coordinates"',
    "'coordinates'",
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
