from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scout_energy_models import aggregate_sha256, sha256_file
from scout_runtime_safety_gate_models import (
    SafetyLnLevelCandidate,
    SafetyLnTransitionCandidate,
)
from scout_runtime_safety_reducer import ReducerRecommendation, ReducerState
from scout_runtime_safety_state_store import (
    RuntimeSafetyStateSnapshot,
    RuntimeSafetyStateSnapshotSummary,
    RuntimeSafetyStateStoreBoundary,
    RuntimeSafetyStateStoreIndex,
    RuntimeSafetyStateStorePrivacy,
    load_runtime_safety_state_snapshot,
    load_runtime_safety_state_store_index,
)


class RuntimeSafetyStateStoreProjectionBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    projection_only: bool = True
    admin_debug_read_only: bool = True
    admin_read_only: bool = True
    local_only: bool = True
    durable_artifact_only: bool = True
    candidate_only: bool = True
    runtime_safety_truth: bool = False
    phase1_runtime_safety_truth: bool = False
    phase1_runtime_mutation_allowed: bool = False
    phase1_l0_l4_state_mutated: bool = False
    safety_api_called: bool = False
    outbound_alert_sent: bool = False
    medical_diagnosis: bool = False
    raw_health_payload_shared: bool = False
    raw_track_shared: bool = False
    raw_gpx_shared: bool = False
    precise_timestamps_shared: bool = False
    home_work_trace_shared: bool = False

    @model_validator(mode="after")
    def enforce_projection_boundary(self) -> "RuntimeSafetyStateStoreProjectionBoundary":
        if not (
            self.projection_only
            and self.admin_debug_read_only
            and self.admin_read_only
            and self.local_only
            and self.durable_artifact_only
            and self.candidate_only
        ):
            raise ValueError("state-store projection must remain read-only candidate evidence")
        if (
            self.runtime_safety_truth
            or self.phase1_runtime_safety_truth
            or self.phase1_runtime_mutation_allowed
            or self.phase1_l0_l4_state_mutated
        ):
            raise ValueError("state-store projection cannot mutate Phase 1 truth")
        if self.safety_api_called:
            raise ValueError("state-store projection cannot call safety APIs")
        if self.outbound_alert_sent:
            raise ValueError("state-store projection cannot send outbound alerts")
        if self.medical_diagnosis:
            raise ValueError("state-store projection cannot be a medical diagnosis")
        if (
            self.raw_health_payload_shared
            or self.raw_track_shared
            or self.raw_gpx_shared
            or self.precise_timestamps_shared
            or self.home_work_trace_shared
        ):
            raise ValueError("state-store projection cannot expose raw private payloads")
        return self


class RuntimeSafetyStateStoreSnapshotProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snapshot_id: str = Field(min_length=1)
    snapshot_path: str = Field(min_length=1)
    sha256: str = Field(min_length=1)
    reducer_sha256: str = Field(min_length=1)
    phase1_adapter_sha256: str | None = None
    phase1_adapter_status: str | None = None
    route_id: str | None = None
    segment_id: str | None = None
    checkpoint_id: str | None = None
    selected_gate_id: str | None = None
    reducer_state: ReducerState
    recommendation: ReducerRecommendation
    ln_level_candidate: SafetyLnLevelCandidate
    ln_transition_candidate: SafetyLnTransitionCandidate
    gate_event_count: int = Field(ge=0)
    contributing_gate_ids: list[str] = Field(default_factory=list)
    corroborating_gate_ids: list[str] = Field(default_factory=list)
    map_target_ids: list[str] = Field(default_factory=list)
    route_pressure_review_required: bool = False
    eta_delay_minutes: int = Field(default=0, ge=0)


class RuntimeSafetyStateStoreProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_runtime_state_store_replay_projection"
    artifact_version: str = "runtime_safety_state_store_projection.v1"
    status: Literal["ready", "missing", "error"]
    project_id: str
    surface_targets: list[str] = Field(default_factory=lambda: ["/admin/debug", "/admin"])
    source_provider: str = "scout_runtime_safety_state_store"
    source_path: str = ""
    sha256: str | None = None
    state_store_dir_path: str | None = None
    latest_snapshot_id: str | None = None
    latest_reducer_sha256: str | None = None
    latest_ln_level_candidate: SafetyLnLevelCandidate | None = None
    latest_reducer_state: ReducerState | None = None
    latest_selected_gate_id: str | None = None
    latest_route_id: str | None = None
    latest_segment_id: str | None = None
    latest_checkpoint_id: str | None = None
    snapshot_count: int = Field(default=0, ge=0)
    snapshots: list[RuntimeSafetyStateStoreSnapshotProjection] = Field(default_factory=list)
    latest_snapshot: RuntimeSafetyStateStoreSnapshotProjection | None = None
    source_refs: list[str] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)
    data_quality: dict[str, Any] = Field(default_factory=dict)
    privacy: dict[str, Any] = Field(default_factory=dict)
    boundary: RuntimeSafetyStateStoreProjectionBoundary = Field(
        default_factory=RuntimeSafetyStateStoreProjectionBoundary
    )
    error_type: str | None = None
    error: str | None = None

    @model_validator(mode="after")
    def enforce_projection_counts(self) -> "RuntimeSafetyStateStoreProjection":
        if self.snapshot_count != len(self.snapshots):
            raise ValueError("snapshot_count must match snapshots")
        if self.latest_snapshot is not None and not self.latest_snapshot_id:
            raise ValueError("latest snapshot detail requires latest snapshot id")
        return self


def build_runtime_safety_state_store_projection(
    project_id: str,
    *,
    project_root: Path | str,
    state_store_index_ref: str | None = None,
    state_store_dir_ref: str | None = None,
    shadow_replay_result_ref: str | None = None,
    surface_targets: list[str] | None = None,
) -> RuntimeSafetyStateStoreProjection:
    root = Path(project_root).expanduser()
    targets = surface_targets or ["/admin/debug", "/admin"]
    try:
        loaded = _load_index_and_latest_snapshot(
            root,
            state_store_index_ref=state_store_index_ref,
            state_store_dir_ref=state_store_dir_ref,
            shadow_replay_result_ref=shadow_replay_result_ref,
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        return RuntimeSafetyStateStoreProjection(
            status="error",
            project_id=project_id,
            surface_targets=targets,
            source_path=str(
                state_store_index_ref
                or state_store_dir_ref
                or shadow_replay_result_ref
                or ""
            ),
            error_type=type(exc).__name__,
            error=str(exc),
            counts={"snapshot_count": 0, "event_count": 0},
        )
    if loaded is None:
        return RuntimeSafetyStateStoreProjection(
            status="missing",
            project_id=project_id,
            surface_targets=targets,
            source_path=str(
                state_store_index_ref
                or state_store_dir_ref
                or shadow_replay_result_ref
                or ""
            ),
            counts={"snapshot_count": 0, "event_count": 0},
        )

    index, latest_snapshot, source_path, state_store_dir_path, source_refs = loaded
    snapshots = [
        _snapshot_projection(summary, latest_snapshot=latest_snapshot)
        for summary in index.snapshots
    ]
    latest = snapshots[-1] if snapshots else None
    digest = aggregate_sha256(
        [
            {
                "project_id": project_id,
                "source_path": source_path,
                "index_sha256": index.sha256,
                "latest_snapshot_id": index.latest_snapshot_id,
                "snapshot_ids": [item.snapshot_id for item in snapshots],
            }
        ]
    )
    boundary = _projection_boundary(index.boundary)
    return RuntimeSafetyStateStoreProjection(
        status="ready",
        project_id=project_id,
        surface_targets=targets,
        source_path=source_path,
        sha256=digest,
        state_store_dir_path=state_store_dir_path,
        latest_snapshot_id=index.latest_snapshot_id,
        latest_reducer_sha256=index.latest_reducer_sha256,
        latest_ln_level_candidate=index.latest_ln_level_candidate,
        latest_reducer_state=index.latest_reducer_state,
        latest_selected_gate_id=latest.selected_gate_id if latest else None,
        latest_route_id=latest.route_id if latest else None,
        latest_segment_id=latest.segment_id if latest else None,
        latest_checkpoint_id=latest.checkpoint_id if latest else None,
        snapshot_count=index.snapshot_count,
        snapshots=snapshots,
        latest_snapshot=latest,
        source_refs=_unique_string_list(
            [
                source_path,
                state_store_dir_path,
                *source_refs,
                index.source_path,
                index.sha256,
                latest.sha256 if latest else None,
            ]
        ),
        counts={
            "snapshot_count": index.snapshot_count,
            "event_count": 1 if latest else 0,
            "map_target_count": len(latest.map_target_ids) if latest else 0,
        },
        data_quality=index.data_quality.model_dump(mode="json"),
        privacy=_projection_privacy(index.privacy).model_dump(mode="json"),
        boundary=boundary,
    )


def runtime_safety_state_store_projection_events(
    projection: RuntimeSafetyStateStoreProjection | dict[str, Any],
    *,
    project_id: str,
    start_sequence: int,
) -> list[dict[str, Any]]:
    projection_model = (
        projection
        if isinstance(projection, RuntimeSafetyStateStoreProjection)
        else RuntimeSafetyStateStoreProjection.model_validate(projection)
    )
    if projection_model.status != "ready" or projection_model.latest_snapshot is None:
        return []
    latest = projection_model.latest_snapshot
    source_refs = _unique_string_list(projection_model.source_refs)
    map_target_ids = _unique_string_list(
        [
            latest.segment_id,
            latest.checkpoint_id,
            *latest.map_target_ids,
        ]
    )
    boundary = {
        **projection_model.boundary.model_dump(mode="json"),
        "projection_only": True,
        "runtime_safety_truth": False,
        "phase1_runtime_safety_truth": False,
        "phase1_l0_l4_state_mutated": False,
        "safety_api_called": False,
        "medical_diagnosis": False,
    }
    payload = {
        "project_id": project_id,
        "profile": "runtime_state_store_replay_projection",
        "projection_event_type": "runtime_safety_state_store_snapshot",
        "import_stage": "runtime_safety_state_store_projection",
        "gate": "multi_gate_safety_reducer",
        "projection_only": True,
        "runtime_safety_truth": False,
        "snapshot_id": latest.snapshot_id,
        "snapshot_sha256": latest.sha256,
        "selected_gate_id": latest.selected_gate_id,
        "state": latest.reducer_state,
        "recommendation": latest.recommendation,
        "ln_level_candidate": latest.ln_level_candidate,
        "ln_transition_candidate": latest.ln_transition_candidate,
        "route_id": latest.route_id,
        "segment_id": latest.segment_id,
        "checkpoint_id": latest.checkpoint_id,
        "gate_event_count": latest.gate_event_count,
        "eta_delay_minutes": latest.eta_delay_minutes,
        "source_refs": source_refs,
        "map_target_ids": map_target_ids,
        "surface_targets": projection_model.surface_targets,
        "boundary": boundary,
    }
    return [
        {
            "event_id": f"debug_event.runtime_safety_state_store.{project_id}.{start_sequence:06d}",
            "session_id": f"pretrip_projection.{project_id}.runtime_safety_state_store",
            "mission_id": project_id,
            "sequence": start_sequence,
            "timestamp": "offset:runtime-safety-state-store",
            "phase": "phase35",
            "kind": "runtime_safety_state_store_snapshot",
            "severity": runtime_safety_state_store_event_severity(latest.ln_level_candidate),
            "summary": (
                "Runtime safety state-store replay snapshot: "
                f"{latest.recommendation}"
            ),
            "subject_ref": latest.snapshot_id,
            "correlation_refs": _unique_string_list(
                [
                    *source_refs,
                    *map_target_ids,
                    latest.selected_gate_id,
                ]
            ),
            "source_refs": source_refs,
            "map_refs": map_target_ids,
            "payload": payload,
        }
    ]


def runtime_safety_state_store_event_severity(level: Any) -> str:
    token = str(level or "")
    if "L4" in token:
        return "critical"
    if "L3" in token or "L2" in token:
        return "warning"
    return "info"


def _load_index_and_latest_snapshot(
    project_root: Path,
    *,
    state_store_index_ref: str | None,
    state_store_dir_ref: str | None,
    shadow_replay_result_ref: str | None,
) -> tuple[
    RuntimeSafetyStateStoreIndex,
    RuntimeSafetyStateSnapshot | None,
    str,
    str | None,
    list[str],
] | None:
    index_ref_candidates = [
        state_store_index_ref,
        "outputs/runtime_safety_state_store/runtime_safety_state_store_index.json",
        "outputs/runtime_shadow_replay/runtime_safety_state_store/runtime_safety_state_store_index.json",
    ]
    dir_ref_candidates = [
        state_store_dir_ref,
        "outputs/runtime_safety_state_store",
        "outputs/runtime_shadow_replay/runtime_safety_state_store",
    ]
    shadow_ref_candidates = [
        shadow_replay_result_ref,
        "outputs/runtime_shadow_replay/runtime_shadow_replay_result.json",
    ]

    for index_ref in index_ref_candidates:
        index_path = _project_ref_path(project_root, index_ref)
        if index_path is None or not index_path.exists():
            continue
        index = load_runtime_safety_state_store_index(index_path)
        store_dir = _matching_state_store_dir(project_root, index_path, dir_ref_candidates)
        latest = _load_latest_snapshot_from_index(index, store_dir)
        return (
            index,
            latest,
            _ref_label(project_root, index_path, index_ref),
            _ref_label(project_root, store_dir, state_store_dir_ref) if store_dir else None,
            _unique_string_list([index_ref, state_store_dir_ref]),
        )

    for dir_ref in dir_ref_candidates:
        store_dir = _project_ref_path(project_root, dir_ref)
        if store_dir is None or not store_dir.exists() or not store_dir.is_dir():
            continue
        index_path = store_dir / "runtime_safety_state_store_index.json"
        if not index_path.exists():
            continue
        index = load_runtime_safety_state_store_index(index_path)
        latest = _load_latest_snapshot_from_index(index, store_dir)
        return (
            index,
            latest,
            _ref_label(project_root, index_path, None),
            _ref_label(project_root, store_dir, dir_ref),
            _unique_string_list([dir_ref]),
        )

    for shadow_ref in shadow_ref_candidates:
        shadow_path = _project_ref_path(project_root, shadow_ref)
        if shadow_path is None or not shadow_path.exists():
            continue
        payload = _load_json(shadow_path)
        index_payload = payload.get("state_store_index")
        if not isinstance(index_payload, dict):
            continue
        index = RuntimeSafetyStateStoreIndex.model_validate(index_payload)
        latest_payload = payload.get("state_snapshot")
        latest = (
            RuntimeSafetyStateSnapshot.model_validate(latest_payload)
            if isinstance(latest_payload, dict)
            else None
        )
        source_path = f"{_ref_label(project_root, shadow_path, shadow_ref)}#state_store_index"
        return (
            index,
            latest,
            source_path,
            None,
            _unique_string_list([shadow_ref, payload.get("sha256")]),
        )
    return None


def _matching_state_store_dir(
    project_root: Path,
    index_path: Path,
    dir_ref_candidates: list[str | None],
) -> Path | None:
    if index_path.name == "runtime_safety_state_store_index.json":
        parent = index_path.parent
        if (parent / "snapshots").exists():
            return parent
    for dir_ref in dir_ref_candidates:
        path = _project_ref_path(project_root, dir_ref)
        if path is not None and path.exists() and (path / "snapshots").exists():
            return path
    return None


def _load_latest_snapshot_from_index(
    index: RuntimeSafetyStateStoreIndex,
    state_store_dir: Path | None,
) -> RuntimeSafetyStateSnapshot | None:
    if state_store_dir is None or not index.latest_snapshot_id or not index.snapshots:
        return None
    latest = index.snapshots[-1]
    snapshot_path = state_store_dir / latest.snapshot_path
    if not snapshot_path.exists():
        snapshot_path = state_store_dir / "snapshots" / f"{index.latest_snapshot_id}.json"
    if not snapshot_path.exists():
        return None
    return load_runtime_safety_state_snapshot(snapshot_path)


def _snapshot_projection(
    summary: RuntimeSafetyStateSnapshotSummary,
    *,
    latest_snapshot: RuntimeSafetyStateSnapshot | None,
) -> RuntimeSafetyStateStoreSnapshotProjection:
    phase1_adapter_status = None
    if latest_snapshot is not None and latest_snapshot.snapshot_id == summary.snapshot_id:
        phase1_adapter_status = latest_snapshot.phase1_adapter_status
    return RuntimeSafetyStateStoreSnapshotProjection(
        **summary.model_dump(mode="json"),
        phase1_adapter_status=phase1_adapter_status,
    )


def _projection_boundary(
    store_boundary: RuntimeSafetyStateStoreBoundary,
) -> RuntimeSafetyStateStoreProjectionBoundary:
    payload = store_boundary.model_dump(mode="json")
    return RuntimeSafetyStateStoreProjectionBoundary(
        local_only=payload.get("local_only", True),
        durable_artifact_only=payload.get("durable_artifact_only", True),
        candidate_only=payload.get("candidate_only", True),
        runtime_safety_truth=False,
        phase1_runtime_safety_truth=False,
        phase1_runtime_mutation_allowed=False,
        phase1_l0_l4_state_mutated=False,
        safety_api_called=False,
        outbound_alert_sent=False,
        medical_diagnosis=False,
        raw_health_payload_shared=False,
        raw_track_shared=False,
        raw_gpx_shared=False,
        precise_timestamps_shared=False,
        home_work_trace_shared=False,
    )


def _projection_privacy(
    store_privacy: RuntimeSafetyStateStorePrivacy,
) -> RuntimeSafetyStateStorePrivacy:
    payload = store_privacy.model_dump(mode="json")
    return RuntimeSafetyStateStorePrivacy(
        local_only=payload.get("local_only", True),
        aggregate_only=payload.get("aggregate_only", True),
        raw_health_payload_shared=False,
        raw_track_shared=False,
        raw_gpx_shared=False,
        precise_timestamps_shared=False,
        home_work_trace_shared=False,
        shareable_by_default=False,
    )


def _project_ref_path(project_root: Path, ref: str | None) -> Path | None:
    if not ref:
        return None
    path = Path(str(ref)).expanduser()
    return path if path.is_absolute() else project_root / path


def _ref_label(project_root: Path, path: Path, original_ref: str | None) -> str:
    if original_ref:
        return str(original_ref)
    try:
        return str(path.resolve().relative_to(project_root.resolve()))
    except ValueError:
        return str(path)


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object at {path}")
    payload.setdefault("sha256", sha256_file(path))
    return payload


def _unique_string_list(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value is None or value == "":
            continue
        item = str(value)
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result
