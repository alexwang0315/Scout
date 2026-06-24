from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scout_energy_models import aggregate_sha256, sha256_file
from scout_runtime_safety_gate_models import (
    SafetyGateConfidence,
    SafetyLnLevelCandidate,
    SafetyLnTransitionCandidate,
)
from scout_runtime_safety_reducer import (
    ReducerRecommendation,
    ReducerState,
    RuntimeSafetyPhase1AdapterResult,
    RuntimeSafetyReducerDecision,
    RuntimeSafetyReducerDataQuality,
)
from scout_wearable_validator import FORBIDDEN_RAW_KEYS


class RuntimeSafetyStateStoreBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    local_only: bool = True
    durable_artifact_only: bool = True
    candidate_only: bool = True
    reducer_owned: bool = True
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
    def enforce_store_boundary(self) -> "RuntimeSafetyStateStoreBoundary":
        if not self.local_only or not self.durable_artifact_only:
            raise ValueError("runtime safety state store is local durable artifact only")
        if not self.candidate_only or not self.reducer_owned:
            raise ValueError("runtime safety state store can only persist reducer candidates")
        if (
            self.runtime_safety_truth
            or self.phase1_runtime_safety_truth
            or self.phase1_runtime_mutation_allowed
            or self.phase1_l0_l4_state_mutated
        ):
            raise ValueError("runtime safety state store cannot mutate or own Phase 1 truth")
        if self.safety_api_called:
            raise ValueError("runtime safety state store cannot call safety APIs")
        if self.outbound_alert_sent:
            raise ValueError("runtime safety state store cannot send outbound alerts")
        if self.medical_diagnosis:
            raise ValueError("runtime safety state store cannot be a medical diagnosis")
        if (
            self.raw_health_payload_shared
            or self.raw_track_shared
            or self.raw_gpx_shared
            or self.precise_timestamps_shared
            or self.home_work_trace_shared
        ):
            raise ValueError("runtime safety state store cannot share raw private payloads")
        return self


class RuntimeSafetyStateStorePrivacy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    local_only: bool = True
    aggregate_only: bool = True
    raw_health_payload_shared: bool = False
    raw_track_shared: bool = False
    raw_gpx_shared: bool = False
    precise_timestamps_shared: bool = False
    home_work_trace_shared: bool = False
    shareable_by_default: bool = False


class RuntimeSafetyStateSnapshotSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snapshot_id: str = Field(min_length=1)
    snapshot_path: str = Field(min_length=1)
    sha256: str = Field(min_length=1)
    reducer_sha256: str = Field(min_length=1)
    phase1_adapter_sha256: str | None = None
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


class RuntimeSafetyStateSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_runtime_safety_state_snapshot"
    artifact_version: str = "runtime_safety_state_snapshot.v1"
    snapshot_id: str = Field(min_length=1)
    source_provider: str = "scout_runtime_safety_state_store"
    source_path: str = Field(min_length=1)
    sha256: str = Field(min_length=1)
    reducer_sha256: str = Field(min_length=1)
    reducer_source_path: str = Field(min_length=1)
    phase1_adapter_sha256: str | None = None
    phase1_adapter_status: str | None = None
    route_id: str | None = None
    segment_id: str | None = None
    checkpoint_id: str | None = None
    selected_gate_id: str | None = None
    selected_event_sha256: str | None = None
    reducer_state: ReducerState
    recommendation: ReducerRecommendation
    proposed_ln_level_candidate: SafetyLnLevelCandidate
    proposed_ln_transition_candidate: SafetyLnTransitionCandidate
    ln_level_candidate: SafetyLnLevelCandidate
    ln_transition_candidate: SafetyLnTransitionCandidate
    route_pressure_review_required: bool = False
    eta_delay_minutes: int = Field(default=0, ge=0)
    gate_event_count: int = Field(ge=0)
    contributing_gate_ids: list[str] = Field(default_factory=list)
    corroborating_gate_ids: list[str] = Field(default_factory=list)
    suppressed_gate_ids: list[str] = Field(default_factory=list)
    map_target_ids: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    policy_trace: list[str] = Field(default_factory=list)
    suppressed_reasons: list[str] = Field(default_factory=list)
    reducer_decision: RuntimeSafetyReducerDecision
    phase1_adapter_result: RuntimeSafetyPhase1AdapterResult | None = None
    data_quality: RuntimeSafetyReducerDataQuality = Field(
        default_factory=RuntimeSafetyReducerDataQuality
    )
    privacy: RuntimeSafetyStateStorePrivacy = Field(
        default_factory=RuntimeSafetyStateStorePrivacy
    )
    boundary: RuntimeSafetyStateStoreBoundary = Field(
        default_factory=RuntimeSafetyStateStoreBoundary
    )

    @model_validator(mode="after")
    def enforce_snapshot_contract(self) -> "RuntimeSafetyStateSnapshot":
        if self.reducer_sha256 != self.reducer_decision.sha256:
            raise ValueError("snapshot reducer sha256 must match reducer decision")
        if self.reducer_source_path != self.reducer_decision.source_path:
            raise ValueError("snapshot reducer source path must match reducer decision")
        if self.reducer_state != self.reducer_decision.reducer_state:
            raise ValueError("snapshot reducer state must match reducer decision")
        if self.recommendation != self.reducer_decision.recommendation:
            raise ValueError("snapshot recommendation must match reducer decision")
        if self.ln_level_candidate != self.reducer_decision.ln_level_candidate:
            raise ValueError("snapshot level must match reducer decision")
        if (
            self.ln_transition_candidate
            != self.reducer_decision.ln_transition_candidate
        ):
            raise ValueError("snapshot transition must match reducer decision")
        if self.phase1_adapter_result is None:
            if self.phase1_adapter_sha256 is not None:
                raise ValueError("adapter sha256 requires adapter result")
        else:
            if self.phase1_adapter_sha256 != self.phase1_adapter_result.sha256:
                raise ValueError("snapshot adapter sha256 must match adapter result")
            if (
                self.phase1_adapter_result.selected_reducer_sha256
                != self.reducer_decision.sha256
            ):
                raise ValueError("adapter result must reference the stored reducer")
            if self.phase1_adapter_result.boundary.phase1_l0_l4_state_mutated:
                raise ValueError("adapter result cannot claim Phase 1 mutation")
            if self.phase1_adapter_result.boundary.safety_api_called:
                raise ValueError("adapter result cannot call safety APIs")
        if (
            self.reducer_decision.boundary.runtime_safety_truth
            or self.reducer_decision.boundary.phase1_l0_l4_state_mutated
            or self.reducer_decision.boundary.safety_api_called
        ):
            raise ValueError("stored reducer must remain candidate-only")
        if self.privacy.raw_health_payload_shared or self.privacy.precise_timestamps_shared:
            raise ValueError("state snapshot privacy flags are invalid")
        forbidden_paths = _forbidden_key_paths(self.model_dump(mode="json"))
        if forbidden_paths:
            raise ValueError(
                "forbidden runtime safety state fields present: "
                + ", ".join(forbidden_paths)
            )
        return self

    def summary(self) -> RuntimeSafetyStateSnapshotSummary:
        return RuntimeSafetyStateSnapshotSummary(
            snapshot_id=self.snapshot_id,
            snapshot_path=self.source_path,
            sha256=self.sha256,
            reducer_sha256=self.reducer_sha256,
            phase1_adapter_sha256=self.phase1_adapter_sha256,
            route_id=self.route_id,
            segment_id=self.segment_id,
            checkpoint_id=self.checkpoint_id,
            selected_gate_id=self.selected_gate_id,
            reducer_state=self.reducer_state,
            recommendation=self.recommendation,
            ln_level_candidate=self.ln_level_candidate,
            ln_transition_candidate=self.ln_transition_candidate,
            gate_event_count=self.gate_event_count,
            contributing_gate_ids=self.contributing_gate_ids,
            corroborating_gate_ids=self.corroborating_gate_ids,
            map_target_ids=self.map_target_ids,
            route_pressure_review_required=self.route_pressure_review_required,
            eta_delay_minutes=self.eta_delay_minutes,
        )


class RuntimeSafetyStateStoreIndex(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_runtime_safety_state_store_index"
    artifact_version: str = "runtime_safety_state_store_index.v1"
    source_provider: str = "scout_runtime_safety_state_store"
    source_path: str = Field(min_length=1)
    sha256: str = Field(min_length=1)
    snapshot_count: int = Field(ge=0)
    latest_snapshot_id: str | None = None
    latest_reducer_sha256: str | None = None
    latest_ln_level_candidate: SafetyLnLevelCandidate | None = None
    latest_reducer_state: ReducerState | None = None
    snapshots: list[RuntimeSafetyStateSnapshotSummary] = Field(default_factory=list)
    data_quality: RuntimeSafetyReducerDataQuality = Field(
        default_factory=RuntimeSafetyReducerDataQuality
    )
    privacy: RuntimeSafetyStateStorePrivacy = Field(
        default_factory=RuntimeSafetyStateStorePrivacy
    )
    boundary: RuntimeSafetyStateStoreBoundary = Field(
        default_factory=RuntimeSafetyStateStoreBoundary
    )

    @model_validator(mode="after")
    def enforce_index_counts(self) -> "RuntimeSafetyStateStoreIndex":
        if self.snapshot_count != len(self.snapshots):
            raise ValueError("snapshot_count must match snapshots")
        if self.snapshots:
            latest = self.snapshots[-1]
            if self.latest_snapshot_id != latest.snapshot_id:
                raise ValueError("latest_snapshot_id must match the latest snapshot")
            if self.latest_reducer_sha256 != latest.reducer_sha256:
                raise ValueError("latest reducer sha256 must match latest snapshot")
            if self.latest_ln_level_candidate != latest.ln_level_candidate:
                raise ValueError("latest level must match latest snapshot")
            if self.latest_reducer_state != latest.reducer_state:
                raise ValueError("latest state must match latest snapshot")
        elif any(
            value is not None
            for value in (
                self.latest_snapshot_id,
                self.latest_reducer_sha256,
                self.latest_ln_level_candidate,
                self.latest_reducer_state,
            )
        ):
            raise ValueError("empty index cannot declare latest snapshot fields")
        return self


class RuntimeSafetyStateStore:
    """File-backed store for reducer candidate state snapshots.

    The store is intentionally local and artifact-only. It records reducer
    candidates for review/replay and never applies Phase 1 transitions.
    """

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root).expanduser()
        self.snapshots_dir = self.root / "snapshots"
        self.index_path = self.root / "runtime_safety_state_store_index.json"
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)

    def save_snapshot(
        self,
        decision: RuntimeSafetyReducerDecision | dict[str, Any],
        *,
        phase1_adapter_result: RuntimeSafetyPhase1AdapterResult
        | dict[str, Any]
        | None = None,
    ) -> RuntimeSafetyStateSnapshot:
        reducer = (
            decision
            if isinstance(decision, RuntimeSafetyReducerDecision)
            else RuntimeSafetyReducerDecision.model_validate(decision)
        )
        adapter = _adapter_model(phase1_adapter_result)
        snapshot_id = _snapshot_id(reducer, adapter)
        path = self.path_for(snapshot_id)
        snapshot = build_runtime_safety_state_snapshot(
            reducer,
            phase1_adapter_result=adapter,
            source_path=_relative_or_string(path, self.root),
            snapshot_id=snapshot_id,
        )
        _atomic_write_json(path, snapshot.model_dump(mode="json"))
        self.write_index()
        return self.load_snapshot(snapshot_id)

    def load_snapshot(self, snapshot_id: str) -> RuntimeSafetyStateSnapshot:
        return load_runtime_safety_state_snapshot(self.path_for(snapshot_id))

    def list_snapshots(
        self,
        *,
        route_id: str | None = None,
        limit: int | None = None,
    ) -> list[RuntimeSafetyStateSnapshot]:
        snapshots = [
            load_runtime_safety_state_snapshot(path)
            for path in sorted(self.snapshots_dir.glob("*.json"))
        ]
        if route_id is not None:
            snapshots = [snapshot for snapshot in snapshots if snapshot.route_id == route_id]
        if limit is not None:
            snapshots = snapshots[-limit:]
        return snapshots

    def latest_snapshot(
        self,
        *,
        route_id: str | None = None,
    ) -> RuntimeSafetyStateSnapshot | None:
        snapshots = self.list_snapshots(route_id=route_id)
        return snapshots[-1] if snapshots else None

    def write_index(self) -> RuntimeSafetyStateStoreIndex:
        index = build_runtime_safety_state_store_index(
            self.list_snapshots(),
            source_path=_relative_or_string(self.index_path, self.root),
        )
        _atomic_write_json(self.index_path, index.model_dump(mode="json"))
        return load_runtime_safety_state_store_index(self.index_path)

    def load_index(self) -> RuntimeSafetyStateStoreIndex:
        if not self.index_path.exists():
            return self.write_index()
        return load_runtime_safety_state_store_index(self.index_path)

    def exists(self, snapshot_id: str) -> bool:
        return self.path_for(snapshot_id).exists()

    def path_for(self, snapshot_id: str) -> Path:
        return self.snapshots_dir / f"{snapshot_id}.json"


def build_runtime_safety_state_snapshot(
    decision: RuntimeSafetyReducerDecision | dict[str, Any],
    *,
    phase1_adapter_result: RuntimeSafetyPhase1AdapterResult | dict[str, Any] | None = None,
    source_path: str = "inline:runtime-safety-state-snapshot",
    snapshot_id: str | None = None,
) -> RuntimeSafetyStateSnapshot:
    reducer = (
        decision
        if isinstance(decision, RuntimeSafetyReducerDecision)
        else RuntimeSafetyReducerDecision.model_validate(decision)
    )
    adapter = _adapter_model(phase1_adapter_result)
    resolved_snapshot_id = snapshot_id or _snapshot_id(reducer, adapter)
    map_target_ids = _unique_string_list(
        [
            target
            for summary in reducer.gate_summaries
            for target in summary.get("map_target_ids", [])
        ]
    )
    evidence_refs = _unique_string_list(
        [
            ref
            for summary in reducer.gate_summaries
            for ref in summary.get("evidence_refs", [])
        ]
    )
    phase1_adapter_sha256 = adapter.sha256 if adapter is not None else None
    digest = aggregate_sha256(
        [
            {
                "snapshot_id": resolved_snapshot_id,
                "source_path": source_path,
                "reducer_sha256": reducer.sha256,
                "phase1_adapter_sha256": phase1_adapter_sha256,
            }
        ]
    )
    return RuntimeSafetyStateSnapshot(
        snapshot_id=resolved_snapshot_id,
        source_path=source_path,
        sha256=digest,
        reducer_sha256=reducer.sha256,
        reducer_source_path=reducer.source_path,
        phase1_adapter_sha256=phase1_adapter_sha256,
        phase1_adapter_status=adapter.status if adapter is not None else None,
        route_id=_first_summary_value(reducer, "route_id"),
        segment_id=_first_summary_value(reducer, "segment_id"),
        checkpoint_id=_first_summary_value(reducer, "checkpoint_id"),
        selected_gate_id=reducer.selected_gate_id,
        selected_event_sha256=reducer.selected_event_sha256,
        reducer_state=reducer.reducer_state,
        recommendation=reducer.recommendation,
        proposed_ln_level_candidate=reducer.proposed_ln_level_candidate,
        proposed_ln_transition_candidate=reducer.proposed_ln_transition_candidate,
        ln_level_candidate=reducer.ln_level_candidate,
        ln_transition_candidate=reducer.ln_transition_candidate,
        route_pressure_review_required=reducer.route_pressure_review_required,
        eta_delay_minutes=reducer.eta_delay_minutes,
        gate_event_count=reducer.gate_event_count,
        contributing_gate_ids=reducer.contributing_gate_ids,
        corroborating_gate_ids=reducer.corroborating_gate_ids,
        suppressed_gate_ids=reducer.suppressed_gate_ids,
        map_target_ids=map_target_ids,
        evidence_refs=evidence_refs,
        policy_trace=reducer.policy_trace,
        suppressed_reasons=reducer.suppressed_reasons,
        reducer_decision=reducer,
        phase1_adapter_result=adapter,
        data_quality=reducer.data_quality,
    )


def build_runtime_safety_state_store_index(
    snapshots: list[RuntimeSafetyStateSnapshot | dict[str, Any]],
    *,
    source_path: str = "inline:runtime-safety-state-store-index",
) -> RuntimeSafetyStateStoreIndex:
    snapshot_models = [
        snapshot
        if isinstance(snapshot, RuntimeSafetyStateSnapshot)
        else RuntimeSafetyStateSnapshot.model_validate(snapshot)
        for snapshot in snapshots
    ]
    summaries = [snapshot.summary() for snapshot in snapshot_models]
    latest = summaries[-1] if summaries else None
    digest = aggregate_sha256(
        [
            {
                "source_path": source_path,
                "snapshot_ids": [summary.snapshot_id for summary in summaries],
                "snapshot_hashes": [summary.sha256 for summary in summaries],
            }
        ]
    )
    return RuntimeSafetyStateStoreIndex(
        source_path=source_path,
        sha256=digest,
        snapshot_count=len(summaries),
        latest_snapshot_id=latest.snapshot_id if latest else None,
        latest_reducer_sha256=latest.reducer_sha256 if latest else None,
        latest_ln_level_candidate=latest.ln_level_candidate if latest else None,
        latest_reducer_state=latest.reducer_state if latest else None,
        snapshots=summaries,
        data_quality=RuntimeSafetyReducerDataQuality(
            confidence=_max_confidence(
                [snapshot.data_quality.confidence for snapshot in snapshot_models]
            ),
            gate_event_count=sum(
                snapshot.data_quality.gate_event_count
                for snapshot in snapshot_models
            ),
            contributing_gate_count=sum(
                snapshot.data_quality.contributing_gate_count
                for snapshot in snapshot_models
            ),
            missing_gate_ids=_unique_string_list(
                [
                    gate_id
                    for snapshot in snapshot_models
                    for gate_id in snapshot.data_quality.missing_gate_ids
                ]
            ),
            stale_signal_names=_unique_string_list(
                [
                    signal
                    for snapshot in snapshot_models
                    for signal in snapshot.data_quality.stale_signal_names
                ]
            ),
            live_network_calls_made=any(
                snapshot.data_quality.live_network_calls_made
                for snapshot in snapshot_models
            ),
            limitations=[
                "local durable reducer candidate store only",
                "index is rebuildable and not runtime safety truth",
            ],
        ),
    )


def write_runtime_safety_state_snapshot(
    snapshot: RuntimeSafetyStateSnapshot,
    output_path: Path | str,
) -> RuntimeSafetyStateSnapshot:
    path = Path(output_path).expanduser()
    _atomic_write_json(path, snapshot.model_dump(mode="json"))
    return load_runtime_safety_state_snapshot(path)


def load_runtime_safety_state_snapshot(path: Path | str) -> RuntimeSafetyStateSnapshot:
    expanded = Path(path).expanduser()
    payload = json.loads(expanded.read_text(encoding="utf-8"))
    payload["source_path"] = payload.get("source_path") or str(expanded)
    payload["sha256"] = payload.get("sha256") or sha256_file(expanded)
    return RuntimeSafetyStateSnapshot.model_validate(payload)


def write_runtime_safety_state_store_index(
    index: RuntimeSafetyStateStoreIndex,
    output_path: Path | str,
) -> RuntimeSafetyStateStoreIndex:
    path = Path(output_path).expanduser()
    _atomic_write_json(path, index.model_dump(mode="json"))
    return load_runtime_safety_state_store_index(path)


def load_runtime_safety_state_store_index(
    path: Path | str,
) -> RuntimeSafetyStateStoreIndex:
    expanded = Path(path).expanduser()
    payload = json.loads(expanded.read_text(encoding="utf-8"))
    payload["source_path"] = payload.get("source_path") or str(expanded)
    payload["sha256"] = payload.get("sha256") or sha256_file(expanded)
    return RuntimeSafetyStateStoreIndex.model_validate(payload)


def _adapter_model(
    value: RuntimeSafetyPhase1AdapterResult | dict[str, Any] | None,
) -> RuntimeSafetyPhase1AdapterResult | None:
    if value is None:
        return None
    if isinstance(value, RuntimeSafetyPhase1AdapterResult):
        return value
    return RuntimeSafetyPhase1AdapterResult.model_validate(value)


def _snapshot_id(
    reducer: RuntimeSafetyReducerDecision,
    adapter: RuntimeSafetyPhase1AdapterResult | None,
) -> str:
    digest = aggregate_sha256(
        [
            {
                "reducer_sha256": reducer.sha256,
                "phase1_adapter_sha256": adapter.sha256 if adapter else None,
            }
        ]
    )
    return f"runtime_safety_state.{digest[:16]}"


def _first_summary_value(
    reducer: RuntimeSafetyReducerDecision,
    key: str,
) -> str | None:
    selected = [
        summary
        for summary in reducer.gate_summaries
        if summary.get("sha256") == reducer.selected_event_sha256
    ]
    candidates = selected or reducer.gate_summaries
    for summary in candidates:
        value = summary.get(key)
        if value:
            return str(value)
    return None


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp_path.replace(path)


def _relative_or_string(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def _forbidden_key_paths(value: Any, prefix: str = "") -> list[str]:
    if isinstance(value, dict):
        paths: list[str] = []
        for key, child in value.items():
            child_path = f"{prefix}.{key}" if prefix else str(key)
            if str(key).lower() in FORBIDDEN_RAW_KEYS:
                paths.append(child_path)
            paths.extend(_forbidden_key_paths(child, child_path))
        return paths
    if isinstance(value, list):
        paths = []
        for index, child in enumerate(value):
            paths.extend(_forbidden_key_paths(child, f"{prefix}[{index}]"))
        return paths
    return []


def _max_confidence(values: list[Any]) -> SafetyGateConfidence:
    rank = {"low": 0, "medium": 1, "high": 2}
    valid = [str(value) for value in values if str(value) in rank]
    if not valid:
        return "low"
    return max(valid, key=lambda item: rank[item])  # type: ignore[return-value]


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
