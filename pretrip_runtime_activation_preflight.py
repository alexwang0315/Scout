from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from mission_graph import load_mission_graph
from pretrip_runtime_artifact_resolution import (
    DEFAULT_RUNTIME_ARTIFACT_RESOLUTION_MANIFEST_NAME,
    load_runtime_artifact_resolution_manifest,
)
from pretrip_runtime_export import (
    DEFAULT_RUNTIME_EXPORT_MANIFEST_NAME,
    RuntimeExportBundleManifest,
    RuntimeExportStatus,
    load_runtime_export_bundle_manifest,
)
from pretrip_runtime_handoff import HandoffTarget, load_runtime_handoff_manifest
from route_matching import load_gpx_route
from runtime_artifact_resolution import resolve_runtime_route_source


class RuntimeActivationPreflightStatus(StrEnum):
    ACTIVATION_READY = "activation_ready"
    ACTIVATION_BLOCKED = "activation_blocked"


class StrictRuntimeActivationPreflightModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RuntimeActivationPreflightFinding(StrictRuntimeActivationPreflightModel):
    finding_id: str = Field(min_length=1)
    severity: Literal["blocker", "info"] = "blocker"
    check_name: str = Field(min_length=1)
    summary: str = Field(min_length=1)


class RuntimeActivationPreflightFiles(StrictRuntimeActivationPreflightModel):
    mission_graph_ref: str
    runtime_handoff_manifest_ref: str
    runtime_export_manifest_ref: str
    runtime_artifact_resolution_manifest_ref: str


class RuntimeActivationPreflightCounts(StrictRuntimeActivationPreflightModel):
    required_manifest_file_count: Literal[4] = 4
    present_manifest_file_count: int = Field(ge=0)
    missing_manifest_file_count: int = Field(ge=0)
    route_artifact_required_count: Literal[1] = 1
    route_artifact_present_count: int = Field(ge=0)
    route_point_count: int = Field(ge=0)
    blocker_count: int = Field(ge=0)
    live_runtime_activation_count: Literal[0] = 0
    safety_api_call_count: Literal[0] = 0
    phase1_live_session_mutation_count: Literal[0] = 0
    phase2_writeback_count: Literal[0] = 0
    raw_payload_copy_count: Literal[0] = 0


class RuntimeActivationPreflightBoundary(StrictRuntimeActivationPreflightModel):
    preflight_only: Literal[True] = True
    live_runtime_activation_allowed: Literal[False] = False
    phase1_live_session_mutation_allowed: Literal[False] = False
    safety_api_calls_allowed: Literal[False] = False
    phase2_writeback_allowed: Literal[False] = False
    raw_payloads_embedded: Literal[False] = False
    requires_explicit_phase1_activation: Literal[True] = True
    notes: list[str] = Field(
        default_factory=lambda: [
            "Runtime Activation Preflight / runtime 啟動前檢查 validates export inputs only.",
            "A ready preflight report is not live activation approval by itself.",
            "Phase 1 runtime must still perform an explicit activation/load step.",
        ]
    )


class RuntimeActivationPreflightReport(StrictRuntimeActivationPreflightModel):
    report_id: str
    artifact_kind: Literal["runtime_activation_preflight_report"] = (
        "runtime_activation_preflight_report"
    )
    status: RuntimeActivationPreflightStatus
    activation_ready: bool
    activation_performed: Literal[False] = False
    project_id: str
    export_id: str
    runtime_target: HandoffTarget
    mission_graph_version: str
    mission_graph_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    route_source_ref: str | None = None
    route_artifact_runtime_ref: str | None = None
    route_point_count: int = Field(ge=0)
    files: RuntimeActivationPreflightFiles
    counts: RuntimeActivationPreflightCounts
    boundary: RuntimeActivationPreflightBoundary = Field(
        default_factory=RuntimeActivationPreflightBoundary
    )
    findings: list[RuntimeActivationPreflightFinding] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_preflight_contract(self) -> "RuntimeActivationPreflightReport":
        blocker_count = sum(1 for finding in self.findings if finding.severity == "blocker")
        if self.counts.blocker_count != blocker_count:
            raise ValueError("blocker_count must match blocker findings")
        if self.status == RuntimeActivationPreflightStatus.ACTIVATION_READY:
            if not self.activation_ready:
                raise ValueError("activation_ready must be true for ready report")
            if blocker_count:
                raise ValueError("activation-ready report cannot contain blockers")
        else:
            if self.activation_ready:
                raise ValueError("blocked report cannot be activation_ready")
        _assert_no_raw_payload_fragments(self.model_dump(mode="json"))
        return self

    def to_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n"


def build_runtime_activation_preflight_report(
    export_root: Path | str,
) -> RuntimeActivationPreflightReport:
    root = Path(export_root)
    export_manifest_path = root / DEFAULT_RUNTIME_EXPORT_MANIFEST_NAME
    runtime_export = load_runtime_export_bundle_manifest(export_manifest_path)
    mission_graph_path = root / "mission_graph.json"
    handoff_path = root / "runtime_handoff_manifest.json"
    resolution_manifest_path = root / DEFAULT_RUNTIME_ARTIFACT_RESOLUTION_MANIFEST_NAME

    findings: list[RuntimeActivationPreflightFinding] = []
    present_manifest_file_count = sum(
        1
        for path in (
            mission_graph_path,
            handoff_path,
            export_manifest_path,
            resolution_manifest_path,
        )
        if path.is_file()
    )
    route_source_ref: str | None = None
    route_artifact_runtime_ref: str | None = None
    route_artifact_present_count = 0
    route_point_count = 0

    if runtime_export.status != RuntimeExportStatus.EXPORTED_NOT_ACTIVATED:
        findings.append(
            _blocker(
                "runtime_export_status_not_ready",
                "runtime_export_status",
                "Runtime export status must be exported_not_activated before preflight.",
            )
        )

    mission_graph = None
    if not mission_graph_path.is_file():
        findings.append(
            _blocker(
                "mission_graph_file_missing",
                "mission_graph_file",
                "MissionGraph runtime input file is missing.",
            )
        )
    else:
        actual_mission_hash = _sha256_file(mission_graph_path)
        if actual_mission_hash != runtime_export.files.mission_graph.sha256:
            findings.append(
                _blocker(
                    "mission_graph_hash_mismatch",
                    "mission_graph_hash",
                    "MissionGraph file hash does not match runtime export manifest.",
                )
            )
        try:
            mission_graph = load_mission_graph(mission_graph_path)
            route_source_ref = mission_graph.route_source
        except Exception as exc:
            findings.append(
                _blocker(
                    "mission_graph_parse_failed",
                    "mission_graph_parse",
                    _safe_summary("MissionGraph file cannot be parsed", exc, root),
                )
            )

    if not handoff_path.is_file():
        findings.append(
            _blocker(
                "runtime_handoff_manifest_missing",
                "runtime_handoff_manifest_file",
                "Runtime handoff manifest file is missing.",
            )
        )
    else:
        actual_handoff_hash = _sha256_file(handoff_path)
        if actual_handoff_hash != runtime_export.files.runtime_handoff_manifest.sha256:
            findings.append(
                _blocker(
                    "runtime_handoff_hash_mismatch",
                    "runtime_handoff_hash",
                    "Runtime handoff file hash does not match runtime export manifest.",
                )
            )
        try:
            handoff = load_runtime_handoff_manifest(handoff_path)
            if handoff.handoff_id != runtime_export.handoff_id:
                findings.append(
                    _blocker(
                        "runtime_handoff_id_mismatch",
                        "runtime_handoff_identity",
                        "Runtime handoff id does not match runtime export manifest.",
                    )
                )
        except Exception as exc:
            findings.append(
                _blocker(
                    "runtime_handoff_parse_failed",
                    "runtime_handoff_parse",
                    _safe_summary("Runtime handoff manifest cannot be parsed", exc, root),
                )
            )

    if not resolution_manifest_path.is_file():
        findings.append(
            _blocker(
                "runtime_artifact_resolution_manifest_missing",
                "runtime_artifact_resolution_manifest_file",
                "Runtime artifact resolution manifest is missing.",
            )
        )
    else:
        try:
            resolution_manifest = load_runtime_artifact_resolution_manifest(
                resolution_manifest_path
            )
            route_artifact_runtime_ref = resolution_manifest.resolutions[0].runtime_ref
            if resolution_manifest.export_id != runtime_export.export_id:
                findings.append(
                    _blocker(
                        "runtime_artifact_resolution_export_mismatch",
                        "runtime_artifact_resolution_identity",
                        "Runtime artifact resolution export id does not match runtime export manifest.",
                    )
                )
            if (
                mission_graph is not None
                and resolution_manifest.route_source_ref != mission_graph.route_source
            ):
                findings.append(
                    _blocker(
                        "runtime_artifact_resolution_route_source_mismatch",
                        "runtime_artifact_resolution_route_source",
                        "Runtime artifact resolution route source does not match MissionGraph.",
                    )
                )
            try:
                route_path = resolve_runtime_route_source(
                    mission_graph_path,
                    resolution_manifest.route_source_ref,
                    resolution_manifest_path,
                )
                route_artifact_present_count = 1
                route = load_gpx_route(route_path)
                route_point_count = len(route.points)
            except FileNotFoundError as exc:
                findings.append(
                    _blocker(
                        _route_file_not_found_id(exc),
                        "route_artifact_resolution",
                        _safe_summary("Runtime route artifact is not ready", exc, root),
                    )
                )
            except ValueError as exc:
                findings.append(
                    _blocker(
                        _route_value_error_id(exc),
                        "route_artifact_resolution",
                        _safe_summary("Runtime route artifact is invalid", exc, root),
                    )
                )
        except Exception as exc:
            findings.append(
                _blocker(
                    "runtime_artifact_resolution_manifest_invalid",
                    "runtime_artifact_resolution_manifest_parse",
                    _safe_summary(
                        "Runtime artifact resolution manifest cannot be parsed",
                        exc,
                        root,
                    ),
                )
            )

    blocker_count = sum(1 for finding in findings if finding.severity == "blocker")
    status = (
        RuntimeActivationPreflightStatus.ACTIVATION_READY
        if blocker_count == 0
        else RuntimeActivationPreflightStatus.ACTIVATION_BLOCKED
    )
    return RuntimeActivationPreflightReport(
        report_id=f"runtime_activation_preflight.{runtime_export.export_id}",
        status=status,
        activation_ready=status == RuntimeActivationPreflightStatus.ACTIVATION_READY,
        project_id=runtime_export.project_id,
        export_id=runtime_export.export_id,
        runtime_target=runtime_export.runtime_target,
        mission_graph_version=runtime_export.mission_graph_version,
        mission_graph_sha256=runtime_export.mission_graph_sha256,
        route_source_ref=route_source_ref,
        route_artifact_runtime_ref=route_artifact_runtime_ref,
        route_point_count=route_point_count,
        files=RuntimeActivationPreflightFiles(
            mission_graph_ref=_export_ref(runtime_export, "mission_graph.json"),
            runtime_handoff_manifest_ref=_export_ref(
                runtime_export,
                "runtime_handoff_manifest.json",
            ),
            runtime_export_manifest_ref=_export_ref(
                runtime_export,
                DEFAULT_RUNTIME_EXPORT_MANIFEST_NAME,
            ),
            runtime_artifact_resolution_manifest_ref=_export_ref(
                runtime_export,
                DEFAULT_RUNTIME_ARTIFACT_RESOLUTION_MANIFEST_NAME,
            ),
        ),
        counts=RuntimeActivationPreflightCounts(
            present_manifest_file_count=present_manifest_file_count,
            missing_manifest_file_count=4 - present_manifest_file_count,
            route_artifact_present_count=route_artifact_present_count,
            route_point_count=route_point_count,
            blocker_count=blocker_count,
        ),
        findings=findings,
    )


def _export_ref(runtime_export: RuntimeExportBundleManifest, name: str) -> str:
    return f"runtime_exports/{runtime_export.export_id}/{name}"


def _blocker(
    finding_id: str,
    check_name: str,
    summary: str,
) -> RuntimeActivationPreflightFinding:
    return RuntimeActivationPreflightFinding(
        finding_id=finding_id,
        check_name=check_name,
        summary=summary,
    )


def _route_file_not_found_id(exc: FileNotFoundError) -> str:
    text = str(exc).lower()
    if "not resolved" in text:
        return "route_artifact_unresolved"
    if "missing" in text:
        return "route_artifact_missing"
    return "route_artifact_not_found"


def _route_value_error_id(exc: ValueError) -> str:
    text = str(exc).lower()
    if "hash mismatch" in text:
        return "route_artifact_hash_mismatch"
    return "route_artifact_invalid"


def _safe_summary(prefix: str, exc: Exception, export_root: Path) -> str:
    text = str(exc).replace(str(export_root.resolve()), "<runtime_export_root>")
    return f"{prefix}: {text}"


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _assert_no_raw_payload_fragments(payload: Any) -> None:
    for text in _walk_strings(payload):
        lowered = text.lower()
        if any(fragment in lowered for fragment in _FORBIDDEN_LOWERCASE_FRAGMENTS):
            raise ValueError("forbidden runtime activation preflight fragment")


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
    "/private/",
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
