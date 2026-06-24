from __future__ import annotations

import json
import platform
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scout_energy_models import aggregate_sha256, sha256_file
from scout_runtime_route_gate_feeds import (
    RuntimeRouteGateFeedInput,
    RuntimeRouteGateFeedResult,
    build_route_gate_events_from_progress_feed,
    write_route_gate_feed_result,
)
from scout_runtime_safety_gate_models import (
    SafetyGateDataQuality,
    ScoutRuntimeSafetyGateEvent,
    ScoutRuntimeSafetyGateEventBatch,
    build_runtime_safety_gate_event_batch,
)
from scout_runtime_safety_reducer import (
    RuntimeSafetyPhase1AdapterResult,
    RuntimeSafetyReducerDecision,
    RuntimeSafetyReducerHysteresisInput,
    build_phase1_adapter_result,
    reduce_runtime_safety_gate_events,
    write_phase1_adapter_result,
    write_runtime_safety_reducer_decision,
)
from scout_runtime_safety_state_store import (
    RuntimeSafetyStateSnapshot,
    RuntimeSafetyStateStore,
    RuntimeSafetyStateStoreIndex,
)
from scout_wearable_validator import FORBIDDEN_RAW_KEYS


class RuntimeShadowReplayBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    local_only: bool = True
    macos_supported: bool = True
    pi_hardware_required: bool = False
    hardware_driver_invoked: bool = False
    live_network_calls_made: bool = False
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
    def enforce_shadow_replay_boundary(self) -> "RuntimeShadowReplayBoundary":
        if not self.local_only or not self.macos_supported:
            raise ValueError("shadow replay must be local and macOS-safe")
        if self.pi_hardware_required or self.hardware_driver_invoked:
            raise ValueError("shadow replay cannot require or invoke Scout hardware")
        if self.live_network_calls_made:
            raise ValueError("shadow replay cannot make live network calls")
        if (
            self.runtime_safety_truth
            or self.phase1_runtime_safety_truth
            or self.phase1_runtime_mutation_allowed
            or self.phase1_l0_l4_state_mutated
        ):
            raise ValueError("shadow replay cannot mutate or own Phase 1 truth")
        if self.safety_api_called:
            raise ValueError("shadow replay cannot call safety APIs")
        if self.outbound_alert_sent:
            raise ValueError("shadow replay cannot send outbound alerts")
        if self.medical_diagnosis:
            raise ValueError("shadow replay cannot be a medical diagnosis")
        if (
            self.raw_health_payload_shared
            or self.raw_track_shared
            or self.raw_gpx_shared
            or self.precise_timestamps_shared
            or self.home_work_trace_shared
        ):
            raise ValueError("shadow replay cannot share raw private payloads")
        return self


class RuntimeShadowReplayPrivacy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    local_only: bool = True
    aggregate_only: bool = True
    raw_health_payload_shared: bool = False
    raw_track_shared: bool = False
    raw_gpx_shared: bool = False
    precise_timestamps_shared: bool = False
    home_work_trace_shared: bool = False
    shareable_by_default: bool = False


class RuntimeShadowReplayInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_runtime_shadow_replay_input"
    artifact_version: str = "runtime_shadow_replay_input.v1"
    source_provider: str = "scout_runtime_shadow_replay_fixture"
    source_path: str = "inline:runtime-shadow-replay"
    route_gate_feed: RuntimeRouteGateFeedInput | None = None
    additional_gate_events: list[ScoutRuntimeSafetyGateEvent] = Field(default_factory=list)
    hysteresis_input: RuntimeSafetyReducerHysteresisInput | None = None
    phase1_adapter_enabled: bool = False
    human_review_approved: bool = False
    data_quality: SafetyGateDataQuality = Field(default_factory=SafetyGateDataQuality)
    privacy: RuntimeShadowReplayPrivacy = Field(default_factory=RuntimeShadowReplayPrivacy)
    boundary: RuntimeShadowReplayBoundary = Field(default_factory=RuntimeShadowReplayBoundary)

    @model_validator(mode="after")
    def enforce_shadow_replay_input(self) -> "RuntimeShadowReplayInput":
        if self.route_gate_feed is None and not self.additional_gate_events:
            raise ValueError("shadow replay requires route gate feed or gate events")
        if self.privacy.raw_health_payload_shared or self.privacy.precise_timestamps_shared:
            raise ValueError("shadow replay privacy flags are invalid")
        forbidden_paths = _forbidden_key_paths(self.model_dump(mode="json"))
        if forbidden_paths:
            raise ValueError(
                "forbidden shadow replay fields present: "
                + ", ".join(forbidden_paths)
            )
        return self


class RuntimeShadowReplayArtifactRefs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    route_gate_feed_result_path: str | None = None
    event_batch_path: str
    reducer_decision_path: str
    phase1_adapter_result_path: str
    state_snapshot_path: str
    state_store_index_path: str
    shadow_replay_result_path: str


class RuntimeShadowReplayResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_runtime_shadow_replay_result"
    artifact_version: str = "runtime_shadow_replay_result.v1"
    source_provider: str = "scout_runtime_shadow_replay"
    source_path: str
    sha256: str
    local_platform: str
    output_dir: str
    route_gate_feed_result: RuntimeRouteGateFeedResult | None = None
    event_batch: ScoutRuntimeSafetyGateEventBatch
    reducer_decision: RuntimeSafetyReducerDecision
    phase1_adapter_result: RuntimeSafetyPhase1AdapterResult
    state_snapshot: RuntimeSafetyStateSnapshot
    state_store_index: RuntimeSafetyStateStoreIndex
    artifact_refs: RuntimeShadowReplayArtifactRefs
    route_gate_event_count: int = Field(ge=0)
    additional_gate_event_count: int = Field(ge=0)
    event_count: int = Field(ge=0)
    selected_gate_id: str | None = None
    ln_level_candidate: str
    reducer_state: str
    recommendation: str
    data_quality: SafetyGateDataQuality = Field(default_factory=SafetyGateDataQuality)
    privacy: RuntimeShadowReplayPrivacy = Field(default_factory=RuntimeShadowReplayPrivacy)
    boundary: RuntimeShadowReplayBoundary = Field(default_factory=RuntimeShadowReplayBoundary)

    @model_validator(mode="after")
    def enforce_shadow_replay_result(self) -> "RuntimeShadowReplayResult":
        if self.event_count != self.event_batch.event_count:
            raise ValueError("shadow replay event_count must match event batch")
        if self.reducer_decision.gate_event_count != self.event_count:
            raise ValueError("reducer event count must match shadow replay")
        if self.phase1_adapter_result.selected_reducer_sha256 != self.reducer_decision.sha256:
            raise ValueError("adapter result must reference reducer decision")
        if self.state_snapshot.reducer_sha256 != self.reducer_decision.sha256:
            raise ValueError("state snapshot must reference reducer decision")
        if self.state_store_index.latest_snapshot_id != self.state_snapshot.snapshot_id:
            raise ValueError("state store index must include latest snapshot")
        if self.ln_level_candidate != self.reducer_decision.ln_level_candidate:
            raise ValueError("result level must match reducer decision")
        if self.reducer_state != self.reducer_decision.reducer_state:
            raise ValueError("result state must match reducer decision")
        if self.recommendation != self.reducer_decision.recommendation:
            raise ValueError("result recommendation must match reducer decision")
        forbidden_paths = _forbidden_key_paths(self.model_dump(mode="json"))
        if forbidden_paths:
            raise ValueError(
                "forbidden shadow replay result fields present: "
                + ", ".join(forbidden_paths)
            )
        return self


def run_runtime_shadow_replay(
    replay: RuntimeShadowReplayInput | dict[str, Any],
    *,
    output_dir: Path | str,
    state_store_dir: Path | str | None = None,
) -> RuntimeShadowReplayResult:
    replay_input = (
        replay
        if isinstance(replay, RuntimeShadowReplayInput)
        else RuntimeShadowReplayInput.model_validate(replay)
    )
    out_dir = Path(output_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    route_result: RuntimeRouteGateFeedResult | None = None
    route_events: list[ScoutRuntimeSafetyGateEvent] = []
    route_result_path: Path | None = None
    if replay_input.route_gate_feed is not None:
        route_result = build_route_gate_events_from_progress_feed(
            replay_input.route_gate_feed
        )
        route_result_path = out_dir / "runtime_route_gate_feed_result.json"
        route_result = write_route_gate_feed_result(route_result, route_result_path)
        route_events = list(route_result.events)

    events = [*route_events, *replay_input.additional_gate_events]
    event_batch_path = out_dir / "runtime_safety_gate_event_batch.json"
    event_batch = build_runtime_safety_gate_event_batch(
        events,
        source_path=_relative_or_string(event_batch_path, out_dir),
    )
    event_batch = _write_event_batch(event_batch, event_batch_path)

    reducer_path = out_dir / "runtime_safety_reducer_dry_run.json"
    reducer = reduce_runtime_safety_gate_events(
        event_batch,
        source_path=_relative_or_string(reducer_path, out_dir),
        hysteresis_input=replay_input.hysteresis_input,
    )
    reducer = write_runtime_safety_reducer_decision(reducer, reducer_path)

    adapter_path = out_dir / "runtime_safety_phase1_adapter_result.json"
    adapter = build_phase1_adapter_result(
        reducer,
        source_path=_relative_or_string(adapter_path, out_dir),
        phase1_adapter_enabled=replay_input.phase1_adapter_enabled,
        human_review_approved=replay_input.human_review_approved,
    )
    adapter = write_phase1_adapter_result(adapter, adapter_path)

    store = RuntimeSafetyStateStore(state_store_dir or out_dir / "runtime_safety_state_store")
    snapshot = store.save_snapshot(reducer, phase1_adapter_result=adapter)
    index = store.load_index()

    result_path = out_dir / "runtime_shadow_replay_result.json"
    result_digest = aggregate_sha256(
        [
            {
                "source_path": _relative_or_string(result_path, out_dir),
                "event_batch_sha256": event_batch.sha256,
                "reducer_sha256": reducer.sha256,
                "phase1_adapter_sha256": adapter.sha256,
                "state_snapshot_sha256": snapshot.sha256,
                "state_store_index_sha256": index.sha256,
            }
        ]
    )
    result = RuntimeShadowReplayResult(
        source_path=_relative_or_string(result_path, out_dir),
        sha256=result_digest,
        local_platform=platform.system(),
        output_dir=str(out_dir),
        route_gate_feed_result=route_result,
        event_batch=event_batch,
        reducer_decision=reducer,
        phase1_adapter_result=adapter,
        state_snapshot=snapshot,
        state_store_index=index,
        artifact_refs=RuntimeShadowReplayArtifactRefs(
            route_gate_feed_result_path=(
                _relative_or_string(route_result_path, out_dir)
                if route_result_path is not None
                else None
            ),
            event_batch_path=_relative_or_string(event_batch_path, out_dir),
            reducer_decision_path=_relative_or_string(reducer_path, out_dir),
            phase1_adapter_result_path=_relative_or_string(adapter_path, out_dir),
            state_snapshot_path=snapshot.source_path,
            state_store_index_path=_relative_or_string(store.index_path, out_dir),
            shadow_replay_result_path=_relative_or_string(result_path, out_dir),
        ),
        route_gate_event_count=len(route_events),
        additional_gate_event_count=len(replay_input.additional_gate_events),
        event_count=event_batch.event_count,
        selected_gate_id=reducer.selected_gate_id,
        ln_level_candidate=reducer.ln_level_candidate,
        reducer_state=reducer.reducer_state,
        recommendation=reducer.recommendation,
        data_quality=SafetyGateDataQuality(
            confidence=reducer.data_quality.confidence,
            signal_count=event_batch.data_quality.signal_count,
            missing_signal_names=_unique_string_list(
                [
                    *event_batch.data_quality.missing_signal_names,
                    *replay_input.data_quality.missing_signal_names,
                ]
            ),
            stale_signal_names=_unique_string_list(
                [
                    *event_batch.data_quality.stale_signal_names,
                    *replay_input.data_quality.stale_signal_names,
                ]
            ),
            live_network_calls_made=False,
            limitations=[
                "local macOS shadow replay only",
                "does not require Scout hardware",
                "does not mutate Phase 1 safety truth",
            ],
        ),
        privacy=replay_input.privacy,
        boundary=replay_input.boundary,
    )
    _write_json(result_path, result.model_dump(mode="json"))
    return RuntimeShadowReplayResult.model_validate_json(
        result_path.read_text(encoding="utf-8")
    )


def load_runtime_shadow_replay_result(path: Path | str) -> RuntimeShadowReplayResult:
    expanded = Path(path).expanduser()
    payload = json.loads(expanded.read_text(encoding="utf-8"))
    payload["source_path"] = payload.get("source_path") or str(expanded)
    payload["sha256"] = payload.get("sha256") or sha256_file(expanded)
    return RuntimeShadowReplayResult.model_validate(payload)


def _write_event_batch(
    event_batch: ScoutRuntimeSafetyGateEventBatch,
    output_path: Path,
) -> ScoutRuntimeSafetyGateEventBatch:
    _write_json(output_path, event_batch.model_dump(mode="json"))
    return ScoutRuntimeSafetyGateEventBatch.model_validate_json(
        output_path.read_text(encoding="utf-8")
    )


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _relative_or_string(path: Path | None, root: Path) -> str:
    if path is None:
        return ""
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
