from __future__ import annotations

import hashlib
import json
import os
import tempfile
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pretrip_runtime_activation_preflight import (
    RuntimeActivationPreflightReport,
    RuntimeActivationPreflightStatus,
)


DEFAULT_RUNTIME_ACTIVATION_REQUEST_NAME = "runtime_activation_request.json"


class RuntimeActivationRequestStatus(StrEnum):
    REQUESTED_NOT_ACTIVATED = "requested_not_activated"


class StrictRuntimeActivationRequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RuntimeActivationRequestSource(StrictRuntimeActivationRequestModel):
    preflight_report_id: str = Field(min_length=1)
    preflight_report_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    preflight_status: Literal["activation_ready"]
    mission_graph_ref: str = Field(min_length=1)
    runtime_handoff_manifest_ref: str = Field(min_length=1)
    runtime_export_manifest_ref: str = Field(min_length=1)
    runtime_artifact_resolution_manifest_ref: str = Field(min_length=1)


class RuntimeActivationRequestCounts(StrictRuntimeActivationRequestModel):
    preflight_blocker_count: Literal[0] = 0
    runtime_activation_request_count: Literal[1] = 1
    route_point_count: int = Field(ge=0)
    live_runtime_activation_count: Literal[0] = 0
    safety_api_call_count: Literal[0] = 0
    phase1_live_session_mutation_count: Literal[0] = 0
    phase2_writeback_count: Literal[0] = 0
    raw_payload_copy_count: Literal[0] = 0


class RuntimeActivationRequestBoundary(StrictRuntimeActivationRequestModel):
    request_artifact_only: Literal[True] = True
    requires_activation_ready_preflight: Literal[True] = True
    phase4_runtime_load_allowed: Literal[False] = False
    live_runtime_activation_allowed: Literal[False] = False
    phase1_live_session_mutation_allowed: Literal[False] = False
    safety_api_calls_allowed: Literal[False] = False
    phase2_writeback_allowed: Literal[False] = False
    raw_payloads_embedded: Literal[False] = False
    requires_phase1_runtime_revalidation: Literal[True] = True
    requires_runtime_operator_confirmation: Literal[True] = True
    notes: list[str] = Field(
        default_factory=lambda: [
            "Runtime Activation Request / runtime 啟動請求 records operator intent only.",
            "The request asks Phase 1 to load a reviewed MissionGraph after revalidation.",
            "This artifact does not start a live field session by itself.",
        ]
    )


class RuntimeActivationRequest(StrictRuntimeActivationRequestModel):
    request_id: str = Field(min_length=1)
    artifact_kind: Literal["runtime_activation_request"] = "runtime_activation_request"
    status: RuntimeActivationRequestStatus = (
        RuntimeActivationRequestStatus.REQUESTED_NOT_ACTIVATED
    )
    activation_requested: Literal[True] = True
    activation_performed: Literal[False] = False
    project_id: str = Field(min_length=1)
    export_id: str = Field(min_length=1)
    runtime_target: dict[str, Any]
    mission_graph_version: str = Field(min_length=1)
    mission_graph_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    route_source_ref: str | None = None
    route_artifact_runtime_ref: str | None = None
    route_point_count: int = Field(ge=0)
    requested_by: str = Field(min_length=1)
    requested_at: str = Field(min_length=1)
    request_reason: str = Field(min_length=1)
    source: RuntimeActivationRequestSource
    counts: RuntimeActivationRequestCounts
    boundary: RuntimeActivationRequestBoundary = Field(
        default_factory=RuntimeActivationRequestBoundary
    )

    @model_validator(mode="after")
    def enforce_activation_request_boundary(self) -> "RuntimeActivationRequest":
        if self.counts.route_point_count != self.route_point_count:
            raise ValueError("route_point_count must match request counts")
        _assert_no_raw_payload_fragments(self.model_dump(mode="json"))
        return self

    def to_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n"


def build_runtime_activation_request(
    preflight_report: RuntimeActivationPreflightReport | dict[str, Any],
    *,
    request_id: str,
    requested_by: str,
    requested_at: str,
    request_reason: str,
) -> RuntimeActivationRequest:
    preflight = RuntimeActivationPreflightReport.model_validate(preflight_report)
    _require_ready_preflight(preflight)

    return RuntimeActivationRequest(
        request_id=request_id,
        project_id=preflight.project_id,
        export_id=preflight.export_id,
        runtime_target=preflight.runtime_target.model_dump(mode="json"),
        mission_graph_version=preflight.mission_graph_version,
        mission_graph_sha256=preflight.mission_graph_sha256,
        route_source_ref=preflight.route_source_ref,
        route_artifact_runtime_ref=preflight.route_artifact_runtime_ref,
        route_point_count=preflight.route_point_count,
        requested_by=requested_by,
        requested_at=requested_at,
        request_reason=request_reason,
        source=RuntimeActivationRequestSource(
            preflight_report_id=preflight.report_id,
            preflight_report_sha256=_sha256_json(preflight.model_dump(mode="json")),
            preflight_status=preflight.status.value,
            mission_graph_ref=preflight.files.mission_graph_ref,
            runtime_handoff_manifest_ref=preflight.files.runtime_handoff_manifest_ref,
            runtime_export_manifest_ref=preflight.files.runtime_export_manifest_ref,
            runtime_artifact_resolution_manifest_ref=(
                preflight.files.runtime_artifact_resolution_manifest_ref
            ),
        ),
        counts=RuntimeActivationRequestCounts(
            route_point_count=preflight.route_point_count,
        ),
    )


def write_runtime_activation_request_for_workspace(
    workspace_root: Path | str,
    preflight_report: RuntimeActivationPreflightReport | dict[str, Any],
    *,
    request_id: str,
    requested_by: str,
    requested_at: str,
    request_reason: str,
    output_name: str = DEFAULT_RUNTIME_ACTIVATION_REQUEST_NAME,
) -> RuntimeActivationRequest:
    root = _require_workspace_root(workspace_root)
    preflight = RuntimeActivationPreflightReport.model_validate(preflight_report)
    request = build_runtime_activation_request(
        preflight,
        request_id=request_id,
        requested_by=requested_by,
        requested_at=requested_at,
        request_reason=request_reason,
    )
    output_path = root / "runtime_exports" / preflight.export_id / output_name
    _require_workspace_relative_path(output_path, root, "runtime_activation_request")
    if output_path.exists():
        raise FileExistsError(
            f"runtime activation request already exists: {output_path}"
        )
    if not output_path.parent.is_dir():
        raise FileNotFoundError(f"runtime export root missing: {output_path.parent}")

    _replace_json(output_path, request.to_json())
    return request


def load_runtime_activation_request(path: Path | str) -> RuntimeActivationRequest:
    return RuntimeActivationRequest.model_validate_json(
        Path(path).read_text(encoding="utf-8")
    )


def _require_ready_preflight(preflight: RuntimeActivationPreflightReport) -> None:
    if preflight.status != RuntimeActivationPreflightStatus.ACTIVATION_READY:
        raise ValueError("runtime activation request requires activation-ready preflight")
    if not preflight.activation_ready:
        raise ValueError("runtime activation request requires activation-ready preflight")
    if preflight.activation_performed:
        raise ValueError("runtime activation request rejects performed activation")
    if preflight.counts.blocker_count != 0:
        raise ValueError("runtime activation request rejects preflight blockers")
    if not preflight.boundary.requires_explicit_phase1_activation:
        raise ValueError("runtime activation request requires explicit Phase 1 activation boundary")


def _require_workspace_root(workspace_root: Path | str) -> Path:
    root = Path(workspace_root)
    if not (root / "project.json").is_file():
        raise FileNotFoundError(f"workspace project.json missing under {root}")
    resolved = root.resolve()
    parts = resolved.parts
    if "tests" in parts and "fixtures" in parts and "pretrip" in parts:
        raise ValueError("runtime activation request must be written to a copied workspace")
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


def _sha256_json(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _assert_no_raw_payload_fragments(payload: Any) -> None:
    for text in _walk_strings(payload):
        lowered = text.lower()
        if any(fragment in lowered for fragment in _FORBIDDEN_LOWERCASE_FRAGMENTS):
            raise ValueError("forbidden runtime activation request fragment")


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
