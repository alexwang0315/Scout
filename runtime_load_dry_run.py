from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from mission_graph import MissionGraphRuntime, load_mission_graph
from pretrip_runtime_activation_preflight import (
    RuntimeActivationPreflightStatus,
    build_runtime_activation_preflight_report,
)
from pretrip_runtime_activation_request import (
    DEFAULT_RUNTIME_ACTIVATION_REQUEST_NAME,
    RuntimeActivationRequest,
    RuntimeActivationRequestStatus,
    load_runtime_activation_request,
)
from pretrip_runtime_artifact_resolution import (
    DEFAULT_RUNTIME_ARTIFACT_RESOLUTION_MANIFEST_NAME,
)
from pretrip_runtime_export import DEFAULT_RUNTIME_EXPORT_MANIFEST_NAME
from route_matching import load_gpx_route
from runtime_artifact_resolution import resolve_runtime_route_source


class RuntimeLoadDryRunStatus(StrEnum):
    DRY_RUN_PASSED = "dry_run_passed"
    DRY_RUN_BLOCKED = "dry_run_blocked"


class StrictRuntimeLoadDryRunModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RuntimeLoadDryRunFinding(StrictRuntimeLoadDryRunModel):
    finding_id: str = Field(min_length=1)
    severity: Literal["blocker", "info"] = "blocker"
    check_name: str = Field(min_length=1)
    summary: str = Field(min_length=1)


class RuntimeLoadDryRunFiles(StrictRuntimeLoadDryRunModel):
    mission_graph_ref: str
    runtime_handoff_manifest_ref: str
    runtime_export_manifest_ref: str
    runtime_artifact_resolution_manifest_ref: str
    runtime_activation_request_ref: str


class RuntimeLoadMissionGraphIndex(StrictRuntimeLoadDryRunModel):
    checkpoint_count: int = Field(ge=0)
    segment_count: int = Field(ge=0)
    control_zone_count: int = Field(ge=0)
    recording_policy_count: int = Field(ge=0)
    first_checkpoint_id: str | None = None
    last_checkpoint_id: str | None = None
    duplicate_id_count: int = Field(ge=0)
    segment_reference_error_count: int = Field(ge=0)


class RuntimeLoadDryRunCounts(StrictRuntimeLoadDryRunModel):
    required_file_count: Literal[5] = 5
    present_file_count: int = Field(ge=0)
    missing_file_count: int = Field(ge=0)
    route_point_count: int = Field(ge=0)
    checkpoint_count: int = Field(ge=0)
    segment_count: int = Field(ge=0)
    control_zone_count: int = Field(ge=0)
    recording_policy_count: int = Field(ge=0)
    duplicate_id_count: int = Field(ge=0)
    segment_reference_error_count: int = Field(ge=0)
    mission_graph_runtime_index_count: int = Field(ge=0)
    blocker_count: int = Field(ge=0)
    safety_runtime_session_count: Literal[0] = 0
    live_runtime_activation_count: Literal[0] = 0
    safety_api_call_count: Literal[0] = 0
    phase1_live_session_mutation_count: Literal[0] = 0
    phase2_writeback_count: Literal[0] = 0
    raw_payload_copy_count: Literal[0] = 0


class RuntimeLoadDryRunBoundary(StrictRuntimeLoadDryRunModel):
    dry_run_only: Literal[True] = True
    phase1_runtime_loader_check: Literal[True] = True
    mission_graph_runtime_index_allowed: Literal[True] = True
    live_runtime_activation_allowed: Literal[False] = False
    safety_runtime_session_allowed: Literal[False] = False
    phase1_live_session_mutation_allowed: Literal[False] = False
    safety_api_calls_allowed: Literal[False] = False
    phase2_writeback_allowed: Literal[False] = False
    raw_payloads_embedded: Literal[False] = False
    requires_explicit_final_activation: Literal[True] = True
    notes: list[str] = Field(
        default_factory=lambda: [
            "Runtime Load Dry Run / runtime 載入演練 validates loader inputs only.",
            "MissionGraphRuntime indexing is allowed for dry-run validation.",
            "SafetyRuntimeSession creation and live safety APIs remain closed.",
        ]
    )


class RuntimeLoadDryRunReport(StrictRuntimeLoadDryRunModel):
    report_id: str
    artifact_kind: Literal["runtime_load_dry_run_report"] = (
        "runtime_load_dry_run_report"
    )
    status: RuntimeLoadDryRunStatus
    dry_run_passed: bool
    activation_performed: Literal[False] = False
    project_id: str
    export_id: str
    request_id: str | None = None
    runtime_target: dict[str, Any] | None = None
    mission_graph_version: str | None = None
    mission_graph_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    route_source_ref: str | None = None
    route_artifact_runtime_ref: str | None = None
    route_point_count: int = Field(ge=0)
    files: RuntimeLoadDryRunFiles
    mission_graph_index: RuntimeLoadMissionGraphIndex
    counts: RuntimeLoadDryRunCounts
    boundary: RuntimeLoadDryRunBoundary = Field(default_factory=RuntimeLoadDryRunBoundary)
    findings: list[RuntimeLoadDryRunFinding] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_dry_run_contract(self) -> "RuntimeLoadDryRunReport":
        blocker_count = sum(1 for finding in self.findings if finding.severity == "blocker")
        if self.counts.blocker_count != blocker_count:
            raise ValueError("blocker_count must match blocker findings")
        if self.status == RuntimeLoadDryRunStatus.DRY_RUN_PASSED:
            if not self.dry_run_passed:
                raise ValueError("dry_run_passed must be true for passed report")
            if blocker_count:
                raise ValueError("passed dry run cannot contain blockers")
        else:
            if self.dry_run_passed:
                raise ValueError("blocked dry run cannot be passed")
        _assert_no_raw_payload_fragments(self.model_dump(mode="json"))
        return self

    def to_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n"


def build_runtime_load_dry_run_report(export_root: Path | str) -> RuntimeLoadDryRunReport:
    root = Path(export_root)
    export_id = root.name
    request_path = root / DEFAULT_RUNTIME_ACTIVATION_REQUEST_NAME
    mission_graph_path = root / "mission_graph.json"
    handoff_path = root / "runtime_handoff_manifest.json"
    export_manifest_path = root / DEFAULT_RUNTIME_EXPORT_MANIFEST_NAME
    resolution_manifest_path = root / DEFAULT_RUNTIME_ARTIFACT_RESOLUTION_MANIFEST_NAME
    findings: list[RuntimeLoadDryRunFinding] = []

    request: RuntimeActivationRequest | None = None
    if not request_path.is_file():
        findings.append(
            _blocker(
                "runtime_activation_request_missing",
                "runtime_activation_request_file",
                "Runtime activation request file is missing.",
            )
        )
    else:
        try:
            request = load_runtime_activation_request(request_path)
            export_id = request.export_id
            if request.status != RuntimeActivationRequestStatus.REQUESTED_NOT_ACTIVATED:
                findings.append(
                    _blocker(
                        "runtime_activation_request_status_not_ready",
                        "runtime_activation_request_status",
                        "Runtime activation request must be requested_not_activated.",
                    )
                )
            if request.activation_performed:
                findings.append(
                    _blocker(
                        "runtime_activation_request_already_performed",
                        "runtime_activation_request_activation_state",
                        "Runtime activation request has already been performed.",
                    )
                )
        except Exception as exc:
            findings.append(
                _blocker(
                    "runtime_activation_request_parse_failed",
                    "runtime_activation_request_parse",
                    _safe_summary("Runtime activation request cannot be parsed", exc, root),
                )
            )

    preflight = None
    try:
        preflight = build_runtime_activation_preflight_report(root)
        if preflight.status != RuntimeActivationPreflightStatus.ACTIVATION_READY:
            findings.append(
                _blocker(
                    "activation_preflight_not_ready",
                    "runtime_activation_preflight",
                    "Runtime activation preflight must be activation_ready.",
                )
            )
            for preflight_finding in preflight.findings:
                findings.append(
                    _blocker(
                        preflight_finding.finding_id,
                        preflight_finding.check_name,
                        preflight_finding.summary,
                    )
                )
    except Exception as exc:
        findings.append(
            _blocker(
                "activation_preflight_rebuild_failed",
                "runtime_activation_preflight",
                _safe_summary("Runtime activation preflight cannot be rebuilt", exc, root),
            )
        )

    if request is not None and preflight is not None:
        _compare_request_to_preflight(request, preflight, findings)

    index = RuntimeLoadMissionGraphIndex(
        checkpoint_count=0,
        segment_count=0,
        control_zone_count=0,
        recording_policy_count=0,
        duplicate_id_count=0,
        segment_reference_error_count=0,
    )
    route_point_count = 0
    mission_graph_runtime_index_count = 0
    if preflight is not None and preflight.activation_ready:
        try:
            graph = load_mission_graph(mission_graph_path)
            runtime = MissionGraphRuntime(graph)
            mission_graph_runtime_index_count = 1
            duplicate_id_count = _duplicate_id_count(
                [checkpoint.checkpoint_id for checkpoint in graph.checkpoints],
                [segment.segment_id for segment in graph.segments],
                [zone.zone_id for zone in graph.control_zones],
                [policy.policy_id for policy in graph.recording_policies],
            )
            segment_reference_error_count = _segment_reference_error_count(runtime)
            index = RuntimeLoadMissionGraphIndex(
                checkpoint_count=len(graph.checkpoints),
                segment_count=len(graph.segments),
                control_zone_count=len(graph.control_zones),
                recording_policy_count=len(graph.recording_policies),
                first_checkpoint_id=(
                    graph.checkpoints[0].checkpoint_id if graph.checkpoints else None
                ),
                last_checkpoint_id=(
                    graph.checkpoints[-1].checkpoint_id if graph.checkpoints else None
                ),
                duplicate_id_count=duplicate_id_count,
                segment_reference_error_count=segment_reference_error_count,
            )
            if duplicate_id_count:
                findings.append(
                    _blocker(
                        "mission_graph_duplicate_ids",
                        "mission_graph_runtime_index",
                        "MissionGraph contains duplicate runtime ids.",
                    )
                )
            if segment_reference_error_count:
                findings.append(
                    _blocker(
                        "mission_graph_segment_reference_error",
                        "mission_graph_runtime_index",
                        "MissionGraph segment references cannot all be resolved.",
                    )
                )
            route_path = resolve_runtime_route_source(
                mission_graph_path,
                graph.route_source,
                resolution_manifest_path,
            )
            route_point_count = len(load_gpx_route(route_path).points)
        except Exception as exc:
            findings.append(
                _blocker(
                    "runtime_loader_dry_run_failed",
                    "runtime_loader_dry_run",
                    _safe_summary("Runtime loader dry run failed", exc, root),
                )
            )

    blocker_count = sum(1 for finding in findings if finding.severity == "blocker")
    status = (
        RuntimeLoadDryRunStatus.DRY_RUN_PASSED
        if blocker_count == 0
        else RuntimeLoadDryRunStatus.DRY_RUN_BLOCKED
    )
    present_file_count = sum(
        1
        for path in (
            mission_graph_path,
            handoff_path,
            export_manifest_path,
            resolution_manifest_path,
            request_path,
        )
        if path.is_file()
    )
    return RuntimeLoadDryRunReport(
        report_id=f"runtime_load_dry_run.{export_id}",
        status=status,
        dry_run_passed=status == RuntimeLoadDryRunStatus.DRY_RUN_PASSED,
        project_id=(
            request.project_id
            if request is not None
            else preflight.project_id
            if preflight is not None
            else "unknown"
        ),
        export_id=export_id,
        request_id=request.request_id if request is not None else None,
        runtime_target=(
            request.runtime_target
            if request is not None
            else preflight.runtime_target.model_dump(mode="json")
            if preflight is not None
            else None
        ),
        mission_graph_version=(
            request.mission_graph_version
            if request is not None
            else preflight.mission_graph_version
            if preflight is not None
            else None
        ),
        mission_graph_sha256=(
            request.mission_graph_sha256
            if request is not None
            else preflight.mission_graph_sha256
            if preflight is not None
            else None
        ),
        route_source_ref=(
            request.route_source_ref
            if request is not None
            else preflight.route_source_ref
            if preflight is not None
            else None
        ),
        route_artifact_runtime_ref=(
            request.route_artifact_runtime_ref
            if request is not None
            else preflight.route_artifact_runtime_ref
            if preflight is not None
            else None
        ),
        route_point_count=route_point_count,
        files=RuntimeLoadDryRunFiles(
            mission_graph_ref=_export_ref(export_id, "mission_graph.json"),
            runtime_handoff_manifest_ref=_export_ref(
                export_id,
                "runtime_handoff_manifest.json",
            ),
            runtime_export_manifest_ref=_export_ref(
                export_id,
                DEFAULT_RUNTIME_EXPORT_MANIFEST_NAME,
            ),
            runtime_artifact_resolution_manifest_ref=_export_ref(
                export_id,
                DEFAULT_RUNTIME_ARTIFACT_RESOLUTION_MANIFEST_NAME,
            ),
            runtime_activation_request_ref=_export_ref(
                export_id,
                DEFAULT_RUNTIME_ACTIVATION_REQUEST_NAME,
            ),
        ),
        mission_graph_index=index,
        counts=RuntimeLoadDryRunCounts(
            present_file_count=present_file_count,
            missing_file_count=5 - present_file_count,
            route_point_count=route_point_count,
            checkpoint_count=index.checkpoint_count,
            segment_count=index.segment_count,
            control_zone_count=index.control_zone_count,
            recording_policy_count=index.recording_policy_count,
            duplicate_id_count=index.duplicate_id_count,
            segment_reference_error_count=index.segment_reference_error_count,
            mission_graph_runtime_index_count=mission_graph_runtime_index_count,
            blocker_count=blocker_count,
        ),
        findings=findings,
    )


def _compare_request_to_preflight(
    request: RuntimeActivationRequest,
    preflight: Any,
    findings: list[RuntimeLoadDryRunFinding],
) -> None:
    preflight_sha = _sha256_json(preflight.model_dump(mode="json"))
    if request.source.preflight_report_sha256 != preflight_sha:
        findings.append(
            _blocker(
                "runtime_activation_request_preflight_hash_mismatch",
                "runtime_activation_request_preflight_hash",
                "Runtime activation request preflight hash does not match rebuilt preflight.",
            )
        )
    if request.source.preflight_report_id != preflight.report_id:
        findings.append(
            _blocker(
                "runtime_activation_request_preflight_id_mismatch",
                "runtime_activation_request_preflight_identity",
                "Runtime activation request preflight id does not match rebuilt preflight.",
            )
        )
    if request.export_id != preflight.export_id:
        findings.append(
            _blocker(
                "runtime_activation_request_export_mismatch",
                "runtime_activation_request_export",
                "Runtime activation request export id does not match rebuilt preflight.",
            )
        )
    if request.mission_graph_sha256 != preflight.mission_graph_sha256:
        findings.append(
            _blocker(
                "runtime_activation_request_mission_graph_hash_mismatch",
                "runtime_activation_request_mission_graph_hash",
                "Runtime activation request MissionGraph hash does not match rebuilt preflight.",
            )
        )
    if request.route_source_ref != preflight.route_source_ref:
        findings.append(
            _blocker(
                "runtime_activation_request_route_source_mismatch",
                "runtime_activation_request_route_source",
                "Runtime activation request route source does not match rebuilt preflight.",
            )
        )
    if request.route_artifact_runtime_ref != preflight.route_artifact_runtime_ref:
        findings.append(
            _blocker(
                "runtime_activation_request_route_artifact_mismatch",
                "runtime_activation_request_route_artifact",
                "Runtime activation request route artifact does not match rebuilt preflight.",
            )
        )


def _export_ref(export_id: str, name: str) -> str:
    return f"runtime_exports/{export_id}/{name}"


def _duplicate_id_count(*id_groups: list[str]) -> int:
    duplicate_count = 0
    for ids in id_groups:
        duplicate_count += len(ids) - len(set(ids))
    return duplicate_count


def _segment_reference_error_count(runtime: MissionGraphRuntime) -> int:
    error_count = 0
    for segment in runtime.graph.segments:
        try:
            runtime.checkpoint(segment.from_checkpoint_id)
            runtime.checkpoint(segment.to_checkpoint_id)
            runtime.control_zone(segment.control_zone_id)
            runtime.recording_policy(segment.recording_policy_id)
        except KeyError:
            error_count += 1
    return error_count


def _blocker(
    finding_id: str,
    check_name: str,
    summary: str,
) -> RuntimeLoadDryRunFinding:
    return RuntimeLoadDryRunFinding(
        finding_id=finding_id,
        check_name=check_name,
        summary=summary,
    )


def _safe_summary(prefix: str, exc: Exception, export_root: Path) -> str:
    text = str(exc).replace(str(export_root.resolve()), "<runtime_export_root>")
    return f"{prefix}: {text}"


def _sha256_json(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _assert_no_raw_payload_fragments(payload: Any) -> None:
    for text in _walk_strings(payload):
        lowered = text.lower()
        if any(fragment in lowered for fragment in _FORBIDDEN_LOWERCASE_FRAGMENTS):
            raise ValueError("forbidden runtime load dry-run fragment")


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
