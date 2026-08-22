from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scout_energy_models import (
    ScoutEnergyDataQuality,
    ScoutEnergyPrivacy,
    aggregate_sha256,
    sha256_file,
)
from scout_runtime_physiologic_integration import (
    PHYSIOLOGIC_GATE_EVIDENCE_JSONL,
    PHYSIOLOGIC_REDUCER_DRY_RUN_FILENAME,
    PHYSIOLOGIC_SAFETY_GATE_EVENT_FILENAME,
    SENSORLOGGER_GATE_INPUTS_FILENAME,
    SENSORLOGGER_WINDOWED_REPLAY_FILENAME,
)
from scout_wearable_validator import FORBIDDEN_RAW_KEYS


PhysiologicTimelineEventKind = Literal[
    "physiologic_gate_window",
    "physiologic_gate_safety_event",
    "physiologic_gate_reducer_dry_run",
    "physiologic_review_capsule",
]
PhysiologicTimelinePhase = Literal["phase35", "phase4"]
PhysiologicTimelineSeverity = Literal["debug", "info", "warning", "error"]


class PhysiologicTimelineBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    projection_only: bool = True
    medical_diagnosis: bool = False
    runtime_safety_truth: bool = False
    phase1_runtime_safety_truth: bool = False
    phase1_runtime_mutation_allowed: bool = False
    phase1_l0_l4_state_mutated: bool = False
    safety_api_called: bool = False
    outbound_alert_sent: bool = False
    raw_health_payload_shared: bool = False
    raw_track_shared: bool = False
    exact_timestamps_shared: bool = False
    home_work_trace_shared: bool = False

    @model_validator(mode="after")
    def enforce_boundary(self) -> "PhysiologicTimelineBoundary":
        if self.medical_diagnosis:
            raise ValueError("physiologic timeline projection cannot be a medical diagnosis")
        if self.runtime_safety_truth or self.phase1_runtime_safety_truth:
            raise ValueError("physiologic timeline projection cannot be runtime safety truth")
        if self.phase1_runtime_mutation_allowed or self.phase1_l0_l4_state_mutated:
            raise ValueError("physiologic timeline projection cannot mutate Phase 1")
        if self.safety_api_called:
            raise ValueError("physiologic timeline projection cannot call safety APIs")
        if self.outbound_alert_sent:
            raise ValueError("physiologic timeline projection cannot send outbound alerts")
        if self.raw_health_payload_shared or self.raw_track_shared or self.exact_timestamps_shared:
            raise ValueError("physiologic timeline projection must stay privacy-preserving")
        return self


class PhysiologicTimelineEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    mission_id: str | None = None
    timestamp: str = Field(min_length=1)
    sequence: int = Field(ge=1)
    kind: PhysiologicTimelineEventKind
    source: str = "scout_runtime_physiologic_timeline"
    phase: PhysiologicTimelinePhase = "phase35"
    severity: PhysiologicTimelineSeverity = "info"
    subject_ref: str | None = None
    correlation_refs: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    map_refs: list[str] = Field(default_factory=list)
    summary: str = Field(min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def enforce_privacy_boundary(self) -> "PhysiologicTimelineEvent":
        if not self.timestamp.startswith("offset:"):
            raise ValueError("physiologic timeline event timestamp must be an offset label")
        forbidden_paths = _forbidden_key_paths(
            self.payload,
            allowed_leaf_keys={"timestamp"},
        )
        if forbidden_paths:
            raise ValueError(f"forbidden raw physiologic timeline payload fields present: {', '.join(forbidden_paths)}")
        payload_boundary = self.payload.get("boundary")
        if isinstance(payload_boundary, dict):
            PhysiologicTimelineBoundary.model_validate(payload_boundary)
        return self


class PhysiologicTimelineProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_physiologic_timeline_projection"
    artifact_version: str = "physiologic_timeline_projection.v1"
    source_provider: str = "scout_runtime_physiologic_timeline"
    source_path: str
    sha256: str
    session_id: str
    mission_id: str | None = None
    event_count: int = Field(ge=0)
    events: list[PhysiologicTimelineEvent]
    counts: dict[str, Any] = Field(default_factory=dict)
    source_artifacts: dict[str, str | None] = Field(default_factory=dict)
    data_quality: ScoutEnergyDataQuality = Field(default_factory=ScoutEnergyDataQuality)
    privacy: ScoutEnergyPrivacy = Field(default_factory=ScoutEnergyPrivacy)
    boundary: PhysiologicTimelineBoundary = Field(default_factory=PhysiologicTimelineBoundary)

    @model_validator(mode="after")
    def enforce_projection(self) -> "PhysiologicTimelineProjection":
        if self.event_count != len(self.events):
            raise ValueError("event_count must match events")
        if self.privacy.raw_health_payload_shared or self.privacy.exact_timestamps_shared:
            raise ValueError("physiologic timeline projection privacy flags are invalid")
        return self


class PhysiologicTimelineArtifacts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_physiologic_timeline_artifacts"
    artifact_version: str = "physiologic_timeline_artifacts.v1"
    source_provider: str = "scout_runtime_physiologic_timeline"
    source_path: str
    sha256: str
    artifact_index: dict[str, Any] | None = None
    windowed_replay: dict[str, Any] | None = None
    gate_input_result: dict[str, Any] | None = None
    gate_outputs: list[dict[str, Any]] = Field(default_factory=list)
    safety_gate_event: dict[str, Any] | None = None
    reducer_dry_run: dict[str, Any] | None = None
    review_capsule: dict[str, Any] | None = None
    source_artifact_paths: dict[str, str | None] = Field(default_factory=dict)
    data_quality: ScoutEnergyDataQuality = Field(default_factory=ScoutEnergyDataQuality)
    privacy: ScoutEnergyPrivacy = Field(default_factory=ScoutEnergyPrivacy)
    boundary: PhysiologicTimelineBoundary = Field(default_factory=PhysiologicTimelineBoundary)


def load_physio_timeline_artifacts(
    *,
    artifact_dir: Path | str | None = None,
    index_path: Path | str | None = None,
    root: Path | str | None = None,
) -> PhysiologicTimelineArtifacts:
    if artifact_dir is None and index_path is None:
        raise ValueError("artifact_dir or index_path is required")
    resolved_index_path = Path(index_path).expanduser() if index_path else Path(artifact_dir).expanduser() / "physiologic_artifact_index.json"
    resolved_artifact_dir = Path(artifact_dir).expanduser() if artifact_dir else resolved_index_path.parent
    root_path = Path(root).expanduser() if root else Path.cwd()

    artifact_index = _load_optional_json(resolved_index_path)
    path_by_role = _path_by_handoff_role(artifact_index, index_path=resolved_index_path, root=root_path)

    windowed_replay_path = _first_existing_path(
        [
            path_by_role.get("windowed_replay"),
            resolved_artifact_dir / SENSORLOGGER_WINDOWED_REPLAY_FILENAME,
        ]
    )
    gate_input_path = _first_existing_path(
        [
            path_by_role.get("gate_input"),
            resolved_artifact_dir / SENSORLOGGER_GATE_INPUTS_FILENAME,
        ]
    )
    gate_evidence_path = _first_existing_path([resolved_artifact_dir / PHYSIOLOGIC_GATE_EVIDENCE_JSONL])
    safety_event_path = _first_existing_path(
        [
            path_by_role.get("safety_gate_event"),
            resolved_artifact_dir / PHYSIOLOGIC_SAFETY_GATE_EVENT_FILENAME,
        ]
    )
    dry_run_path = _first_existing_path(
        [
            path_by_role.get("reducer_dry_run"),
            resolved_artifact_dir / PHYSIOLOGIC_REDUCER_DRY_RUN_FILENAME,
        ]
    )
    review_capsule_path = _first_existing_path([path_by_role.get("admin_review_capsule")])

    windowed_replay = _load_optional_json(windowed_replay_path)
    gate_input_result = _load_optional_json(gate_input_path)
    gate_outputs = _load_optional_jsonl(gate_evidence_path)
    safety_gate_event = _load_optional_json(safety_event_path)
    reducer_dry_run = _load_optional_json(dry_run_path)
    review_capsule = _load_optional_json(review_capsule_path)

    for label, payload in (
        ("artifact_index", artifact_index),
        ("windowed_replay", windowed_replay),
        ("gate_input_result", gate_input_result),
        ("safety_gate_event", safety_gate_event),
        ("reducer_dry_run", reducer_dry_run),
        ("review_capsule", review_capsule),
    ):
        if payload is not None:
            _assert_no_forbidden_payload(payload, label=label)
    for index, payload in enumerate(gate_outputs, start=1):
        _assert_no_forbidden_payload(payload, label=f"gate_outputs[{index}]")

    source_artifact_paths = {
        "artifact_index": str(resolved_index_path) if artifact_index is not None else None,
        "windowed_replay": str(windowed_replay_path) if windowed_replay_path else None,
        "gate_inputs": str(gate_input_path) if gate_input_path else None,
        "gate_evidence": str(gate_evidence_path) if gate_evidence_path else None,
        "safety_gate_event": str(safety_event_path) if safety_event_path else None,
        "reducer_dry_run": str(dry_run_path) if dry_run_path else None,
        "review_capsule": str(review_capsule_path) if review_capsule_path else None,
    }
    artifact_sha = aggregate_sha256(
        [
            {
                "artifact_index_sha256": sha256_file(resolved_index_path) if artifact_index is not None else None,
                "windowed_replay_sha256": _sha256_optional(windowed_replay_path),
                "gate_input_sha256": _sha256_optional(gate_input_path),
                "gate_evidence_sha256": _sha256_optional(gate_evidence_path),
                "safety_event_sha256": _sha256_optional(safety_event_path),
                "dry_run_sha256": _sha256_optional(dry_run_path),
                "review_capsule_sha256": _sha256_optional(review_capsule_path),
            }
        ]
    )
    return PhysiologicTimelineArtifacts(
        source_path=str(resolved_index_path if artifact_index is not None else resolved_artifact_dir),
        sha256=artifact_sha,
        artifact_index=artifact_index,
        windowed_replay=windowed_replay,
        gate_input_result=gate_input_result,
        gate_outputs=gate_outputs,
        safety_gate_event=safety_gate_event,
        reducer_dry_run=reducer_dry_run,
        review_capsule=review_capsule,
        source_artifact_paths=source_artifact_paths,
        data_quality=_combined_data_quality(
            [
                windowed_replay,
                gate_input_result,
                *(gate_outputs or []),
                safety_gate_event,
                reducer_dry_run,
                review_capsule,
            ]
        ),
    )


def build_physio_timeline_projection(
    *,
    artifact_dir: Path | str | None = None,
    index_path: Path | str | None = None,
    root: Path | str | None = None,
    session_id: str = "physiologic_timeline_projection.local",
    mission_id: str | None = None,
    sequence_start: int = 1,
) -> PhysiologicTimelineProjection:
    artifacts = load_physio_timeline_artifacts(
        artifact_dir=artifact_dir,
        index_path=index_path,
        root=root,
    )
    events = normalize_physio_timeline_events(
        artifacts,
        session_id=session_id,
        mission_id=mission_id,
        sequence_start=sequence_start,
    )
    projection_sha = aggregate_sha256(
        [
            artifacts.sha256,
            {
                "session_id": session_id,
                "mission_id": mission_id,
                "events": [event.model_dump(mode="json") for event in events],
            },
        ]
    )
    return PhysiologicTimelineProjection(
        source_path=artifacts.source_path,
        sha256=projection_sha,
        session_id=session_id,
        mission_id=mission_id,
        event_count=len(events),
        events=events,
        counts=_projection_counts(events),
        source_artifacts=artifacts.source_artifact_paths,
        data_quality=artifacts.data_quality,
        privacy=ScoutEnergyPrivacy(),
        boundary=PhysiologicTimelineBoundary(),
    )


def normalize_physio_timeline_events(
    artifacts: PhysiologicTimelineArtifacts,
    *,
    session_id: str = "physiologic_timeline_projection.local",
    mission_id: str | None = None,
    sequence_start: int = 1,
) -> list[PhysiologicTimelineEvent]:
    sequence = sequence_start
    events: list[PhysiologicTimelineEvent] = []
    replay_windows = (artifacts.windowed_replay or {}).get("windows") or []
    gate_inputs = (artifacts.gate_input_result or {}).get("gate_inputs") or []
    gate_outputs = artifacts.gate_outputs or []
    gate_output_by_window = {
        _window_index_from_gate_output(output, fallback=index + 1): output
        for index, output in enumerate(gate_outputs)
    }
    gate_input_by_window = {
        _window_index_from_gate_input(item, fallback=index + 1): item
        for index, item in enumerate(gate_inputs)
    }
    safety_event = artifacts.safety_gate_event
    reducer = artifacts.reducer_dry_run
    source_artifact_refs = _source_artifact_refs(artifacts)

    for fallback_index, window in enumerate(replay_windows, start=1):
        window_index = int(window.get("window_index") or fallback_index)
        gate_output = gate_output_by_window.get(window_index)
        gate_input = gate_input_by_window.get(window_index)
        state = str((gate_output or {}).get("state") or "normal")
        route_context = (gate_input or {}).get("route_context") or {}
        map_refs = _map_refs(route_context)
        subject_ref = f"physiologic_gate.window.{window_index:03d}"
        payload = _timeline_payload_boundary(
            {
                "projection_event_type": "physiologic_gate_window",
                "gate": "physiologic_gate",
                "state": state,
                "required_action": (gate_output or {}).get("required_action"),
                "window_index": window_index,
                "elapsed_start_min": window.get("elapsed_start_min"),
                "elapsed_end_min": window.get("elapsed_end_min"),
                "duration_min": window.get("duration_min"),
                "p90_heart_rate_bpm": window.get("p90_heart_rate_bpm"),
                "avg_heart_rate_bpm": window.get("avg_heart_rate_bpm"),
                "max_heart_rate_bpm": window.get("max_heart_rate_bpm"),
                "movement_efficiency_ratio_to_session_reference": window.get(
                    "movement_efficiency_ratio_to_session_reference"
                ),
                "high_hr_low_efficiency_window": window.get("high_hr_low_efficiency_window"),
                "active_energy_kj": window.get("active_energy_kj"),
                "cadence_spm": window.get("cadence_spm"),
                "pace_mps": window.get("pace_mps"),
                "eta_delay_minutes": (gate_output or {}).get("eta_delay_minutes"),
                "route_pressure_review_required": (
                    ((gate_output or {}).get("route_pressure_effect") or {}).get("route_pressure_review_required")
                ),
                "source_refs": _event_source_refs(
                    source_artifact_refs,
                    gate_output=(gate_output or None),
                    safety_event=None,
                    reducer=None,
                ),
                "map_target_ids": map_refs,
                "segment_id": route_context.get("segment_id"),
                "route_id": route_context.get("route_id"),
                "data_quality": (gate_output or {}).get("data_quality") or (artifacts.windowed_replay or {}).get("data_quality"),
            }
        )
        events.append(
            PhysiologicTimelineEvent(
                event_id=f"debug_event.physiologic_gate.window.{window_index:06d}",
                session_id=session_id,
                mission_id=mission_id,
                timestamp=_offset_window_label(window),
                sequence=sequence,
                kind="physiologic_gate_window",
                phase="phase35",
                severity=_event_severity_for_state(state),
                subject_ref=subject_ref,
                correlation_refs=payload["source_refs"],
                source_refs=payload["source_refs"],
                map_refs=map_refs,
                summary=_window_summary(window_index, state, window, gate_output),
                payload=payload,
            )
        )
        sequence += 1

    if safety_event is not None:
        route_context = _last_route_context(gate_inputs)
        map_refs = _map_refs(route_context)
        payload = _timeline_payload_boundary(
            {
                "projection_event_type": "physiologic_gate_safety_event",
                "gate": "physiologic_gate",
                "state_candidate": safety_event.get("state_candidate"),
                "required_action": safety_event.get("required_action"),
                "physiologic_severity": safety_event.get("severity"),
                "ln_transition_candidate": safety_event.get("ln_transition_candidate"),
                "eta_delay_minutes": safety_event.get("eta_delay_minutes"),
                "route_pressure_review_required": safety_event.get("route_pressure_review_required"),
                "safety_reducer_required": safety_event.get("safety_reducer_required"),
                "source_gate_sha256": safety_event.get("source_gate_sha256"),
                "source_refs": _event_source_refs(source_artifact_refs, safety_event=safety_event),
                "map_target_ids": map_refs,
                "segment_id": route_context.get("segment_id"),
                "route_id": route_context.get("route_id"),
                "data_quality": safety_event.get("data_quality"),
            }
        )
        events.append(
            PhysiologicTimelineEvent(
                event_id=f"debug_event.physiologic_gate.safety_event.{sequence:06d}",
                session_id=session_id,
                mission_id=mission_id,
                timestamp=_offset_seconds_label(safety_event.get("observed_at_offset_s")),
                sequence=sequence,
                kind="physiologic_gate_safety_event",
                phase="phase35",
                severity=_event_severity_for_state(str(safety_event.get("state_candidate") or "")),
                subject_ref=safety_event.get("event_id") or "physiologic_gate.safety_event",
                correlation_refs=payload["source_refs"],
                source_refs=payload["source_refs"],
                map_refs=map_refs,
                summary=(
                    "Physiologic gate emitted "
                    f"{safety_event.get('state_candidate', 'unknown')} -> {safety_event.get('ln_transition_candidate', 'none')}"
                ),
                payload=payload,
            )
        )
        sequence += 1

    if reducer is not None:
        route_context = _last_route_context(gate_inputs)
        map_refs = _map_refs(route_context)
        payload = _timeline_payload_boundary(
            {
                "projection_event_type": "physiologic_gate_reducer_dry_run",
                "gate": "physiologic_gate",
                "recommendation": reducer.get("recommendation"),
                "highest_state_candidate": reducer.get("highest_state_candidate"),
                "highest_severity": reducer.get("highest_severity"),
                "ln_transition_candidate": reducer.get("ln_transition_candidate"),
                "route_pressure_review_required": reducer.get("route_pressure_review_required"),
                "selected_event_sha256": reducer.get("selected_event_sha256"),
                "source_refs": _event_source_refs(source_artifact_refs, reducer=reducer),
                "map_target_ids": map_refs,
                "segment_id": route_context.get("segment_id"),
                "route_id": route_context.get("route_id"),
                "data_quality": reducer.get("data_quality"),
            }
        )
        events.append(
            PhysiologicTimelineEvent(
                event_id=f"debug_event.physiologic_gate.reducer_dry_run.{sequence:06d}",
                session_id=session_id,
                mission_id=mission_id,
                timestamp=_offset_seconds_label(None),
                sequence=sequence,
                kind="physiologic_gate_reducer_dry_run",
                phase="phase35",
                severity=_event_severity_for_state(str(reducer.get("highest_state_candidate") or "")),
                subject_ref="physiologic_gate.reducer_dry_run",
                correlation_refs=payload["source_refs"],
                source_refs=payload["source_refs"],
                map_refs=map_refs,
                summary=(
                    "Physiologic reducer dry-run recommendation: "
                    f"{reducer.get('recommendation', 'continue_monitoring')}"
                ),
                payload=payload,
            )
        )
        sequence += 1

    if artifacts.review_capsule is not None:
        capsule = artifacts.review_capsule
        payload = _timeline_payload_boundary(
            {
                "projection_event_type": "physiologic_review_capsule",
                "gate": "physiologic_gate",
                "current_max_gate_state": capsule.get("current_max_gate_state"),
                "trend_direction": capsule.get("trend_direction"),
                "review_candidate_change": capsule.get("review_candidate_change"),
                "review_priority": capsule.get("review_priority"),
                "primary_reasons": capsule.get("primary_reasons") or [],
                "suggested_review_actions": capsule.get("suggested_review_actions") or [],
                "source_refs": _event_source_refs(source_artifact_refs, review_capsule=capsule),
                "map_target_ids": [],
                "data_quality": capsule.get("data_quality"),
            }
        )
        events.append(
            PhysiologicTimelineEvent(
                event_id=f"debug_event.physiologic_gate.review_capsule.{sequence:06d}",
                session_id=session_id,
                mission_id=mission_id,
                timestamp="offset:batch-review",
                sequence=sequence,
                kind="physiologic_review_capsule",
                phase="phase4",
                severity=_review_capsule_severity(capsule.get("review_priority")),
                subject_ref="physiologic_gate.review_capsule",
                correlation_refs=payload["source_refs"],
                source_refs=payload["source_refs"],
                map_refs=[],
                summary=(
                    "Physiologic review capsule: "
                    f"{capsule.get('current_max_gate_state', 'unknown')} / {capsule.get('review_priority', 'none')}"
                ),
                payload=payload,
            )
        )

    return events


def write_physio_timeline_projection(
    *,
    output_path: Path | str,
    artifact_dir: Path | str | None = None,
    index_path: Path | str | None = None,
    root: Path | str | None = None,
    session_id: str = "physiologic_timeline_projection.local",
    mission_id: str | None = None,
    sequence_start: int = 1,
) -> PhysiologicTimelineProjection:
    projection = build_physio_timeline_projection(
        artifact_dir=artifact_dir,
        index_path=index_path,
        root=root,
        session_id=session_id,
        mission_id=mission_id,
        sequence_start=sequence_start,
    )
    path = Path(output_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(projection.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return projection


def _path_by_handoff_role(
    artifact_index: dict[str, Any] | None,
    *,
    index_path: Path,
    root: Path,
) -> dict[str, Path]:
    if not artifact_index:
        return {}
    by_role: dict[str, Path] = {}
    for entry in artifact_index.get("artifacts") or []:
        if not isinstance(entry, dict):
            continue
        role = str(entry.get("handoff_role") or "")
        raw_path = entry.get("path")
        if not role or not raw_path:
            continue
        by_role[role] = _resolve_artifact_path(str(raw_path), index_path=index_path, root=root)
    return by_role


def _resolve_artifact_path(value: str, *, index_path: Path, root: Path) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    for candidate in (root / path, index_path.parent / path):
        if candidate.exists():
            return candidate
    return index_path.parent / path


def _first_existing_path(paths: list[Path | None]) -> Path | None:
    for path in paths:
        if path is not None and path.exists():
            return path
    return None


def _load_optional_json(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object expected: {path}")
    return payload


def _load_optional_jsonl(path: Path | None) -> list[dict[str, Any]]:
    if path is None or not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise ValueError(f"JSON object expected in {path}:{line_number}")
        rows.append(payload)
    return rows


def _assert_no_forbidden_payload(payload: dict[str, Any], *, label: str) -> None:
    forbidden_paths = _forbidden_key_paths(payload)
    if forbidden_paths:
        raise ValueError(f"forbidden raw physiologic artifact fields in {label}: {', '.join(forbidden_paths)}")


def _forbidden_key_paths(
    value: Any,
    prefix: str = "",
    *,
    allowed_leaf_keys: set[str] | None = None,
) -> list[str]:
    allowed_leaf_keys = allowed_leaf_keys or set()
    if isinstance(value, dict):
        paths: list[str] = []
        for key, child in value.items():
            child_path = f"{prefix}.{key}" if prefix else str(key)
            if str(key).lower() in FORBIDDEN_RAW_KEYS and str(key) not in allowed_leaf_keys:
                paths.append(child_path)
            paths.extend(_forbidden_key_paths(child, child_path, allowed_leaf_keys=allowed_leaf_keys))
        return paths
    if isinstance(value, list):
        paths = []
        for index, child in enumerate(value):
            paths.extend(_forbidden_key_paths(child, f"{prefix}[{index}]", allowed_leaf_keys=allowed_leaf_keys))
        return paths
    return []


def _window_index_from_gate_output(output: dict[str, Any], *, fallback: int) -> int:
    elapsed_minutes = ((output.get("observation_window") or {}).get("elapsed_minutes"))
    window_minutes = ((output.get("threshold_policy") or {}).get("observation_window_minutes")) or 15
    if isinstance(elapsed_minutes, int | float) and elapsed_minutes:
        return max(1, round(float(elapsed_minutes) / float(window_minutes)))
    return fallback


def _window_index_from_gate_input(item: dict[str, Any], *, fallback: int) -> int:
    elapsed_s = item.get("observed_at_offset_s")
    window_minutes = ((item.get("observation_window") or {}).get("window_minutes")) or 15
    if isinstance(elapsed_s, int | float) and elapsed_s:
        return max(1, round(float(elapsed_s) / (float(window_minutes) * 60.0)))
    return fallback


def _last_route_context(gate_inputs: list[dict[str, Any]]) -> dict[str, Any]:
    for item in reversed(gate_inputs):
        route_context = item.get("route_context")
        if isinstance(route_context, dict):
            return route_context
    return {}


def _map_refs(route_context: dict[str, Any]) -> list[str]:
    refs = []
    for key in ("segment_id", "checkpoint_id"):
        value = route_context.get(key)
        if value and value not in {"current", "unknown"}:
            refs.append(str(value))
    target_ids = route_context.get("map_target_ids")
    if isinstance(target_ids, list):
        refs.extend(str(item) for item in target_ids if item)
    return sorted(set(refs))


def _source_artifact_refs(artifacts: PhysiologicTimelineArtifacts) -> dict[str, str]:
    return {
        key: value
        for key, value in artifacts.source_artifact_paths.items()
        if value
    }


def _event_source_refs(
    source_artifact_refs: dict[str, str],
    *,
    gate_output: dict[str, Any] | None = None,
    safety_event: dict[str, Any] | None = None,
    reducer: dict[str, Any] | None = None,
    review_capsule: dict[str, Any] | None = None,
) -> list[str]:
    refs = [
        source_artifact_refs.get("artifact_index"),
        source_artifact_refs.get("windowed_replay"),
        source_artifact_refs.get("gate_evidence") if gate_output is not None else None,
        source_artifact_refs.get("safety_gate_event") if safety_event is not None else None,
        source_artifact_refs.get("reducer_dry_run") if reducer is not None else None,
        source_artifact_refs.get("review_capsule") if review_capsule is not None else None,
        gate_output.get("sha256") if gate_output else None,
        safety_event.get("sha256") if safety_event else None,
        reducer.get("sha256") if reducer else None,
        review_capsule.get("sha256") if review_capsule else None,
    ]
    return [str(ref) for ref in refs if ref]


def _timeline_payload_boundary(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        **payload,
        "boundary": PhysiologicTimelineBoundary().model_dump(mode="json"),
        "privacy": ScoutEnergyPrivacy().model_dump(mode="json"),
        "runtime_safety_truth": False,
        "projection_only": True,
    }


def _window_summary(
    window_index: int,
    state: str,
    window: dict[str, Any],
    gate_output: dict[str, Any] | None,
) -> str:
    p90 = window.get("p90_heart_rate_bpm")
    efficiency = window.get("movement_efficiency_ratio_to_session_reference")
    delay = (gate_output or {}).get("eta_delay_minutes")
    parts = [
        f"window {window_index}",
        f"state={state}",
        f"HRp90={p90}" if p90 is not None else None,
        f"eff={efficiency}" if efficiency is not None else None,
        f"ETA+{delay}m" if delay is not None else None,
    ]
    return " | ".join(str(part) for part in parts if part)


def _offset_window_label(window: dict[str, Any]) -> str:
    start = window.get("elapsed_start_min")
    end = window.get("elapsed_end_min")
    if isinstance(start, int | float) and isinstance(end, int | float):
        return f"offset:+{round(float(start)):03d}m-+{round(float(end)):03d}m"
    return "offset:unknown-window"


def _offset_seconds_label(value: Any) -> str:
    if isinstance(value, int | float):
        return f"offset:+{round(float(value)):05d}s"
    return "offset:projection"


def _event_severity_for_state(state: str) -> PhysiologicTimelineSeverity:
    normalized = state.strip().lower()
    if normalized in {"retreat_suggested", "alert_candidate"}:
        return "error"
    if normalized in {"watch", "stop_and_rest"}:
        return "warning"
    return "info"


def _review_capsule_severity(value: Any) -> PhysiologicTimelineSeverity:
    normalized = str(value or "").strip().lower()
    if normalized == "urgent_review":
        return "error"
    if normalized == "review":
        return "warning"
    return "info"


def _projection_counts(events: list[PhysiologicTimelineEvent]) -> dict[str, Any]:
    by_kind: dict[str, int] = {}
    by_state: dict[str, int] = {}
    with_map_ref_count = 0
    for event in events:
        by_kind[event.kind] = by_kind.get(event.kind, 0) + 1
        state = (
            event.payload.get("state")
            or event.payload.get("state_candidate")
            or event.payload.get("highest_state_candidate")
            or event.payload.get("current_max_gate_state")
        )
        if state:
            state_key = str(state)
            by_state[state_key] = by_state.get(state_key, 0) + 1
        if event.map_refs:
            with_map_ref_count += 1
    return {
        "event_count": len(events),
        "by_kind": dict(sorted(by_kind.items())),
        "by_state": dict(sorted(by_state.items())),
        "with_map_ref_count": with_map_ref_count,
        "without_map_ref_count": len(events) - with_map_ref_count,
    }


def _combined_data_quality(payloads: list[dict[str, Any] | None]) -> ScoutEnergyDataQuality:
    qualities = [
        payload.get("data_quality")
        for payload in payloads
        if isinstance(payload, dict) and isinstance(payload.get("data_quality"), dict)
    ]
    return ScoutEnergyDataQuality(
        heart_rate_confidence=_max_confidence([quality.get("heart_rate_confidence") for quality in qualities]),
        gps_confidence=_max_confidence([quality.get("gps_confidence") for quality in qualities]),
        provider_value_confidence=_max_confidence(
            [quality.get("provider_value_confidence") for quality in qualities]
        ),
        limitations=[
            "physiologic timeline projection uses sanitized aggregate artifacts only",
            "timeline timestamps are elapsed-offset labels, not exact timestamps",
        ],
    )


def _max_confidence(values: list[Any]) -> Literal["high", "medium", "low"]:
    rank = {"low": 0, "medium": 1, "high": 2}
    valid = [str(value) for value in values if str(value) in rank]
    if not valid:
        return "low"
    return max(valid, key=lambda item: rank[item])  # type: ignore[return-value]


def _sha256_optional(path: Path | None) -> str | None:
    return sha256_file(path) if path is not None and path.exists() else None
