from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path
from statistics import median
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scout_energy_models import (
    ScoutEnergyBoundary,
    ScoutEnergyDataQuality,
    ScoutEnergyPrivacy,
    aggregate_sha256,
    sha256_file,
)
from scout_runtime_physiologic_gate import (
    PhysiologicBaselineContext,
    PhysiologicGateInput,
    PhysiologicGateOutput,
    PhysiologicGateState,
    PhysiologicRouteContext,
    build_runtime_physiologic_gate,
)
from scout_runtime_physiologic_pipeline import (
    HighHeartRateBurden,
    PhysiologicActivityWindowSummary,
    PhysiologicWindowedActivityReplay,
    WindowRestCostFeature,
    build_gate_inputs_from_windowed_activity_replay,
    build_health_auto_export_physio_analysis,
    build_physio_review_capsule,
    compare_health_auto_export_physio_analyses,
)
from scout_wearable_validator import FORBIDDEN_RAW_KEYS


PHYSIOLOGIC_ARTIFACT_INDEX_FILENAME = "physiologic_artifact_index.json"
PHYSIOLOGIC_GATE_EVIDENCE_JSONL = "physiologic_gate_evidence.jsonl"
PHYSIOLOGIC_GATE_STATUS_FILENAME = "physiologic_gate_status.json"
PHYSIOLOGIC_SAFETY_GATE_EVENT_FILENAME = "physiologic_safety_gate_event.json"
PHYSIOLOGIC_REDUCER_DRY_RUN_FILENAME = "physiologic_reducer_dry_run.json"
HEALTH_AUTO_EXPORT_ANALYSIS_FILENAME = "health_auto_export_physio_analysis.json"
HEALTH_AUTO_EXPORT_DELTA_FILENAME = "health_auto_export_physio_analysis_delta.json"
PHYSIO_REVIEW_CAPSULE_FILENAME = "physio_review_capsule.json"
SENSORLOGGER_WINDOWED_REPLAY_FILENAME = "sensorlogger_physio_windowed_replay.json"
SENSORLOGGER_GATE_INPUTS_FILENAME = "sensorlogger_physio_gate_inputs.json"


SafetyGateSeverity = Literal[
    "none",
    "watch",
    "rest",
    "retreat_review",
    "alert_review",
]
ReducerRecommendation = Literal[
    "continue_monitoring",
    "slow_down",
    "stop_and_rest",
    "retreat_review",
    "alert_review",
]
LnTransitionCandidate = Literal[
    "none",
    "candidate_watch",
    "candidate_rest",
    "candidate_retreat",
    "candidate_alert_review",
]


class PhysiologicArtifactIndexEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str
    artifact_version: str | None = None
    schema_version: str | None = None
    path: str
    sha256: str
    source_provider: str
    source_path: str
    source_sha256: str | None = None
    data_quality: dict[str, Any]
    privacy: dict[str, Any]
    boundary: dict[str, Any]
    handoff_role: str = "review_evidence"


class PhysiologicArtifactIndex(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_physiologic_artifact_index"
    artifact_version: str = "physiologic_artifact_index.v1"
    source_provider: str = "scout_runtime_physiologic_integration"
    source_path: str
    sha256: str
    artifact_count: int = Field(ge=0)
    artifacts: list[PhysiologicArtifactIndexEntry]
    data_quality: ScoutEnergyDataQuality = Field(default_factory=ScoutEnergyDataQuality)
    privacy: ScoutEnergyPrivacy = Field(default_factory=ScoutEnergyPrivacy)
    boundary: ScoutEnergyBoundary = Field(default_factory=ScoutEnergyBoundary)

    @model_validator(mode="after")
    def enforce_boundary(self) -> "PhysiologicArtifactIndex":
        if self.artifact_count != len(self.artifacts):
            raise ValueError("artifact_count must match artifacts")
        return self


class PhysiologicSensorLoggerFrame(BaseModel):
    model_config = ConfigDict(extra="forbid")

    frame_index: int = Field(ge=1)
    elapsed_s: int = Field(ge=0)
    heart_rate_bpm: float | None = Field(default=None, ge=0)
    distance_m: float | None = Field(default=None, ge=0)
    distance_delta_m: float | None = Field(default=None, ge=0)
    active_energy_kj: float | None = Field(default=None, ge=0)
    active_energy_delta_kj: float | None = Field(default=None, ge=0)
    cadence_spm: float | None = Field(default=None, ge=0)
    source_provider: str = "sensorlogger_mqtt_local_jsonl"
    source_line: int = Field(ge=1)


class PhysiologicSafetyGateEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_physiologic_safety_gate_event"
    artifact_version: str = "physiologic_safety_gate_event.v1"
    gate_id: str = "physiologic_gate"
    event_id: str
    source_provider: str
    source_path: str
    sha256: str
    source_gate_sha256: str
    observed_at_offset_s: int = Field(ge=0)
    state_candidate: PhysiologicGateState
    required_action: str
    severity: SafetyGateSeverity
    ln_transition_candidate: LnTransitionCandidate
    eta_delay_minutes: int = Field(ge=0)
    route_pressure_review_required: bool
    dominant_reasons: list[str] = Field(default_factory=list)
    reducer_handoff_allowed: bool = True
    safety_reducer_required: bool
    phase1_l0_l4_state_mutated: bool = False
    safety_api_called: bool = False
    outbound_alert_sent: bool = False
    data_quality: dict[str, Any]
    privacy: ScoutEnergyPrivacy = Field(default_factory=ScoutEnergyPrivacy)
    boundary: ScoutEnergyBoundary = Field(default_factory=ScoutEnergyBoundary)

    @model_validator(mode="after")
    def enforce_handoff_boundary(self) -> "PhysiologicSafetyGateEvent":
        if self.phase1_l0_l4_state_mutated:
            raise ValueError("physiologic safety gate event must not mutate Phase 1 state directly")
        if self.safety_api_called:
            raise ValueError("physiologic safety gate event must not call /safety/*")
        if self.outbound_alert_sent:
            raise ValueError("physiologic safety gate event must not send outbound alerts")
        if self.boundary.medical_diagnosis or self.boundary.provider_values_are_scout_truth:
            raise ValueError("physiologic safety gate event boundary is invalid")
        return self


class PhysiologicReducerDryRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_physiologic_reducer_dry_run"
    artifact_version: str = "physiologic_reducer_dry_run.v1"
    source_provider: str = "scout_runtime_physiologic_integration"
    source_path: str
    sha256: str
    event_count: int = Field(ge=0)
    selected_event_sha256: str | None = None
    highest_state_candidate: PhysiologicGateState | None = None
    highest_severity: SafetyGateSeverity = "none"
    recommendation: ReducerRecommendation = "continue_monitoring"
    ln_transition_candidate: LnTransitionCandidate = "none"
    route_pressure_review_required: bool = False
    phase1_l0_l4_state_mutated: bool = False
    safety_api_called: bool = False
    outbound_alert_sent: bool = False
    event_refs: list[dict[str, Any]] = Field(default_factory=list)
    data_quality: ScoutEnergyDataQuality = Field(default_factory=ScoutEnergyDataQuality)
    privacy: ScoutEnergyPrivacy = Field(default_factory=ScoutEnergyPrivacy)
    boundary: ScoutEnergyBoundary = Field(default_factory=ScoutEnergyBoundary)

    @model_validator(mode="after")
    def enforce_dry_run_boundary(self) -> "PhysiologicReducerDryRun":
        if self.event_count != len(self.event_refs):
            raise ValueError("event_count must match event_refs")
        if self.phase1_l0_l4_state_mutated:
            raise ValueError("reducer dry run cannot mutate Phase 1 state")
        if self.safety_api_called:
            raise ValueError("reducer dry run cannot call /safety/*")
        if self.outbound_alert_sent:
            raise ValueError("reducer dry run cannot send outbound alerts")
        return self


class PhysiologicIntegrationRunResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: str = "scout_physiologic_integration_run_result"
    artifact_version: str = "physiologic_integration_run_result.v1"
    source_provider: str = "scout_runtime_physiologic_integration"
    source_path: str
    sha256: str
    output_dir: str
    window_count: int = Field(ge=0)
    gate_output_count: int = Field(ge=0)
    paths: dict[str, str | None]
    latest_state: PhysiologicGateState | None = None
    reducer_recommendation: ReducerRecommendation = "continue_monitoring"
    data_quality: ScoutEnergyDataQuality = Field(default_factory=ScoutEnergyDataQuality)
    privacy: ScoutEnergyPrivacy = Field(default_factory=ScoutEnergyPrivacy)
    boundary: ScoutEnergyBoundary = Field(default_factory=ScoutEnergyBoundary)


def index_physio_artifacts(
    artifact_paths: list[Path | str],
    *,
    output_path: Path | str | None = None,
    root: Path | str | None = None,
) -> PhysiologicArtifactIndex:
    root_path = Path(root or Path.cwd())
    entries: list[PhysiologicArtifactIndexEntry] = []
    for candidate in artifact_paths:
        path = Path(candidate)
        payload = _load_json(path)
        forbidden_paths = _forbidden_key_paths(payload)
        if forbidden_paths:
            raise ValueError(f"forbidden raw physiologic artifact fields present: {', '.join(forbidden_paths)}")
        entries.append(_artifact_index_entry(path, payload, root=root_path))
    index_source_path = _relpath(Path(output_path), root_path) if output_path else "inline:physiologic-artifact-index"
    index_sha = aggregate_sha256(
        [
            {
                "artifact_kind": "scout_physiologic_artifact_index",
                "artifacts": [entry.model_dump(mode="json") for entry in entries],
            }
        ]
    )
    index = PhysiologicArtifactIndex(
        source_path=index_source_path,
        sha256=index_sha,
        artifact_count=len(entries),
        artifacts=entries,
        data_quality=ScoutEnergyDataQuality(
            heart_rate_confidence=_max_confidence(
                [entry.data_quality.get("heart_rate_confidence") for entry in entries]
            ),
            gps_confidence=_max_confidence([entry.data_quality.get("gps_confidence") for entry in entries]),
            provider_value_confidence=_max_confidence(
                [entry.data_quality.get("provider_value_confidence") for entry in entries]
            ),
            limitations=["index contains artifact references and schema summaries only; raw payloads are not embedded"],
        ),
    )
    if output_path:
        _write_model(Path(output_path), index)
    return index


def write_physio_review_from_health_auto_export(
    current_zip_path: Path | str,
    *,
    output_dir: Path | str,
    previous_zip_path: Path | str | None = None,
    activity_type: Literal["walking", "hiking"] = "walking",
    window_minutes: int = 15,
) -> dict[str, Any]:
    output_root = Path(output_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    current_path = Path(current_zip_path).expanduser()
    previous_path = Path(previous_zip_path).expanduser() if previous_zip_path else None

    analysis = build_health_auto_export_physio_analysis(
        current_path,
        activity_type=activity_type,
        window_minutes=window_minutes,
    )
    analysis_path = output_root / HEALTH_AUTO_EXPORT_ANALYSIS_FILENAME
    _write_model(analysis_path, analysis)
    artifact_paths = [analysis_path]

    delta = None
    delta_path: Path | None = None
    if previous_path is not None:
        previous = build_health_auto_export_physio_analysis(
            previous_path,
            activity_type=activity_type,
            window_minutes=window_minutes,
        )
        delta = compare_health_auto_export_physio_analyses(
            previous,
            analysis,
            source_path=f"{_relpath(previous_path, Path.cwd())}+{_relpath(current_path, Path.cwd())}",
        )
        delta_path = output_root / HEALTH_AUTO_EXPORT_DELTA_FILENAME
        _write_model(delta_path, delta)
        artifact_paths.append(delta_path)

    capsule = build_physio_review_capsule(
        analysis,
        delta=delta,
        source_path=str(analysis_path if delta_path is None else delta_path),
    )
    capsule_path = output_root / PHYSIO_REVIEW_CAPSULE_FILENAME
    _write_model(capsule_path, capsule)
    artifact_paths.append(capsule_path)

    index_path = output_root / PHYSIOLOGIC_ARTIFACT_INDEX_FILENAME
    artifact_index = index_physio_artifacts(artifact_paths, output_path=index_path, root=Path.cwd())

    return {
        "artifact_kind": "scout_physio_review_write_result",
        "artifact_version": "physio_review_write_result.v1",
        "source_provider": "health_auto_export_local_zip",
        "source_path": str(current_path),
        "sha256": aggregate_sha256([analysis.sha256, delta.sha256 if delta else None, capsule.sha256]),
        "paths": {
            "analysis": str(analysis_path),
            "delta": str(delta_path) if delta_path else None,
            "capsule": str(capsule_path),
            "artifact_index": str(index_path),
        },
        "artifact_index": artifact_index.model_dump(mode="json"),
        "data_quality": analysis.data_quality.model_dump(mode="json"),
        "privacy": ScoutEnergyPrivacy().model_dump(mode="json"),
        "boundary": ScoutEnergyBoundary().model_dump(mode="json"),
    }


def load_sensorlogger_frames(
    sensorlogger_vitals_path: Path | str,
    *,
    max_records: int = 1000,
) -> list[PhysiologicSensorLoggerFrame]:
    path = Path(sensorlogger_vitals_path).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"SensorLogger vitals JSONL not found: {path}")

    parsed_rows: list[tuple[int, dict[str, Any]]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        payload = json.loads(line)
        parsed_rows.append((line_number, payload))
        if len(parsed_rows) >= max_records:
            break
    if not parsed_rows:
        return []

    first_timestamp = _first_present_float(
        [_row_value(row, ("timestamp_s", "time_s", "loggingTime", "time")) for _, row in parsed_rows]
    )
    frames: list[PhysiologicSensorLoggerFrame] = []
    for frame_index, (line_number, row) in enumerate(parsed_rows, start=1):
        elapsed_s = _elapsed_seconds_for_row(row, frame_index=frame_index, first_timestamp=first_timestamp)
        values = row.get("values") if isinstance(row.get("values"), dict) else {}
        frames.append(
            PhysiologicSensorLoggerFrame(
                frame_index=frame_index,
                elapsed_s=elapsed_s,
                heart_rate_bpm=_first_present_float(
                    [
                        _row_value(row, ("heart_rate_bpm", "heartRateBPM", "heartRate", "hr", "bpm")),
                        _row_value(values, ("heart_rate_bpm", "heartRateBPM", "heartRate", "hr", "bpm")),
                    ]
                ),
                distance_m=_first_present_float(
                    [
                        _row_value(row, ("distance_m", "pedometerDistance", "walkingAndRunningDistance")),
                        _row_value(values, ("distance_m", "pedometerDistance", "walkingAndRunningDistance")),
                    ]
                ),
                distance_delta_m=_first_present_float(
                    [
                        _row_value(row, ("distance_delta_m", "distanceDeltaM")),
                        _row_value(values, ("distance_delta_m", "distanceDeltaM")),
                    ]
                ),
                active_energy_kj=_first_present_float(
                    [
                        _row_value(row, ("active_energy_kj", "activeEnergyKJ", "activeEnergy", "activeEnergyBurned")),
                        _row_value(values, ("active_energy_kj", "activeEnergyKJ", "activeEnergy", "activeEnergyBurned")),
                    ]
                ),
                active_energy_delta_kj=_first_present_float(
                    [
                        _row_value(row, ("active_energy_delta_kj", "activeEnergyDeltaKJ")),
                        _row_value(values, ("active_energy_delta_kj", "activeEnergyDeltaKJ")),
                    ]
                ),
                cadence_spm=_first_present_float(
                    [
                        _row_value(row, ("cadence_spm", "cadence", "stepCadence", "steps_per_minute")),
                        _row_value(values, ("cadence_spm", "cadence", "stepCadence", "steps_per_minute")),
                    ]
                ),
                source_line=line_number,
            )
        )
    return frames


def build_windowed_replay_from_sensorlogger_jsonl(
    sensorlogger_vitals_path: Path | str,
    *,
    window_minutes: int = 15,
    source_provider: str = "sensorlogger_mqtt_local_jsonl",
    activity_type: Literal["walking", "hiking", "running", "other"] = "hiking",
    reference_pace_mps: float | None = None,
    max_records: int = 1000,
) -> PhysiologicWindowedActivityReplay:
    if window_minutes < 1 or window_minutes > 60:
        raise ValueError("window_minutes must be between 1 and 60")
    path = Path(sensorlogger_vitals_path).expanduser()
    frames = load_sensorlogger_frames(path, max_records=max_records)
    windows = _windows_from_frames(frames, window_minutes=window_minutes, reference_pace_mps=reference_pace_mps)
    paces = [window.pace_mps for window in windows if window.pace_mps is not None and window.pace_mps > 0]
    cadences = [window.cadence_spm for window in windows if window.cadence_spm is not None and window.cadence_spm > 0]
    session_reference_pace = reference_pace_mps or (float(median(paces)) if paces else None)
    session_reference_cadence = float(median(cadences)) if cadences else None
    windows = _apply_window_reference_ratios(windows, reference_pace=session_reference_pace)
    source_sha = sha256_file(path)
    replay_sha = aggregate_sha256(
        [
            source_sha,
            {
                "window_minutes": window_minutes,
                "window_count": len(windows),
                "reference_pace_mps": session_reference_pace,
                "windows": [window.model_dump(mode="json") for window in windows],
            },
        ]
    )
    return PhysiologicWindowedActivityReplay(
        source_provider=source_provider,
        source_path=str(path),
        sha256=replay_sha,
        activity_type=activity_type,
        session_index=1,
        window_minutes=window_minutes,
        window_count=len(windows),
        session_reference_pace_mps=session_reference_pace,
        session_reference_cadence_spm=session_reference_cadence,
        windows=windows,
        data_quality=ScoutEnergyDataQuality(
            heart_rate_confidence="medium" if any(frame.heart_rate_bpm is not None for frame in frames) else "low",
            gps_confidence="low",
            sample_cadence_s=_sample_cadence_seconds(frames),
            provider_value_confidence="medium",
            limitations=[
                "SensorLogger replay is assembled into sanitized elapsed-offset windows",
                "raw SensorLogger rows, exact timestamps, and coordinates are not embedded",
            ],
        ),
        privacy=ScoutEnergyPrivacy(),
        boundary=ScoutEnergyBoundary(),
    )


def run_physio_integration_replay(
    sensorlogger_vitals_path: Path | str,
    *,
    output_dir: Path | str,
    route_context: PhysiologicRouteContext | dict[str, Any] | None = None,
    baseline_context: PhysiologicBaselineContext | dict[str, Any] | None = None,
    baseline_path: Path | str | None = None,
    window_minutes: int = 15,
    activity_type: Literal["walking", "hiking", "running", "other"] = "hiking",
    max_records: int = 1000,
) -> PhysiologicIntegrationRunResult:
    output_root = Path(output_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    baseline = _load_baseline_context(baseline_context=baseline_context, baseline_path=baseline_path)
    route = _route_context(route_context)
    replay = build_windowed_replay_from_sensorlogger_jsonl(
        sensorlogger_vitals_path,
        window_minutes=window_minutes,
        activity_type=activity_type,
        reference_pace_mps=baseline.expected_pace_mps,
        max_records=max_records,
    )
    replay_path = output_root / SENSORLOGGER_WINDOWED_REPLAY_FILENAME
    _write_model(replay_path, replay)

    gate_input_result = build_gate_inputs_from_windowed_activity_replay(
        replay,
        route_context=route,
        baseline=baseline,
    )
    gate_input_path = output_root / SENSORLOGGER_GATE_INPUTS_FILENAME
    _write_json(gate_input_path, gate_input_result)

    gate_outputs: list[PhysiologicGateOutput] = []
    gate_evidence_path = output_root / PHYSIOLOGIC_GATE_EVIDENCE_JSONL
    with gate_evidence_path.open("w", encoding="utf-8") as handle:
        for item in gate_input_result["gate_inputs"]:
            output = build_runtime_physiologic_gate(PhysiologicGateInput.model_validate(item))
            gate_outputs.append(output)
            handle.write(json.dumps(output.model_dump(mode="json"), ensure_ascii=False, sort_keys=True))
            handle.write("\n")

    latest_gate = gate_outputs[-1] if gate_outputs else None
    event = build_safety_gate_event_from_physio_gate(
        latest_gate,
        source_path=str(gate_evidence_path),
    ) if latest_gate else None
    event_path = output_root / PHYSIOLOGIC_SAFETY_GATE_EVENT_FILENAME
    if event is not None:
        _write_model(event_path, event)

    reducer = dry_run_physio_reducer([event] if event else [], source_path=str(event_path if event else gate_evidence_path))
    reducer_path = output_root / PHYSIOLOGIC_REDUCER_DRY_RUN_FILENAME
    _write_model(reducer_path, reducer)

    status_path = output_root / PHYSIOLOGIC_GATE_STATUS_FILENAME
    paths = {
        "windowed_replay": str(replay_path),
        "gate_inputs": str(gate_input_path),
        "gate_evidence": str(gate_evidence_path),
        "safety_gate_event": str(event_path) if event is not None else None,
        "reducer_dry_run": str(reducer_path),
        "status": str(status_path),
    }
    artifact_paths = [
        replay_path,
        gate_input_path,
        reducer_path,
        *([event_path] if event is not None else []),
    ]
    index_path = output_root / PHYSIOLOGIC_ARTIFACT_INDEX_FILENAME
    artifact_index = index_physio_artifacts(artifact_paths, output_path=index_path, root=Path.cwd())
    paths["artifact_index"] = str(index_path)

    result_sha = aggregate_sha256(
        [
            replay.sha256,
            gate_input_result["sha256"],
            [output.sha256 for output in gate_outputs],
            event.sha256 if event else None,
            reducer.sha256,
        ]
    )
    result = PhysiologicIntegrationRunResult(
        source_path=str(sensorlogger_vitals_path),
        sha256=result_sha,
        output_dir=str(output_root),
        window_count=replay.window_count,
        gate_output_count=len(gate_outputs),
        paths=paths,
        latest_state=latest_gate.state if latest_gate else None,
        reducer_recommendation=reducer.recommendation,
        data_quality=ScoutEnergyDataQuality(
            heart_rate_confidence=replay.data_quality.heart_rate_confidence,
            gps_confidence=replay.data_quality.gps_confidence,
            provider_value_confidence=replay.data_quality.provider_value_confidence,
            limitations=[
                *replay.data_quality.limitations,
                "physiologic gate event is reducer handoff evidence only",
                "no direct Phase 1 mutation or safety mutation API call is performed",
            ],
        ),
        privacy=ScoutEnergyPrivacy(),
        boundary=ScoutEnergyBoundary(),
    )
    _write_json(
        status_path,
        {
            **result.model_dump(mode="json"),
            "artifact_index": artifact_index.model_dump(mode="json"),
            "boundary": {
                **result.boundary.model_dump(mode="json"),
                "phase1_l0_l4_state_mutated": False,
                "safety_api_called": False,
                "outbound_alert_sent": False,
            },
        },
    )
    return result


def build_safety_gate_event_from_physio_gate(
    gate_output: PhysiologicGateOutput,
    *,
    source_path: str = "inline:physiologic-gate-output",
) -> PhysiologicSafetyGateEvent:
    severity, ln_transition = _severity_for_state(gate_output.state)
    event_id = f"physiologic_gate_event:{gate_output.sha256[:16]}"
    observed_at_offset_s = gate_output.observation_window.elapsed_minutes * 60
    event_sha = aggregate_sha256(
        [
            gate_output.sha256,
            {
                "event_id": event_id,
                "state_candidate": gate_output.state,
                "severity": severity,
                "ln_transition_candidate": ln_transition,
                "route_pressure_review_required": gate_output.route_pressure_effect.route_pressure_review_required,
                "eta_delay_minutes": gate_output.eta_delay_minutes,
            },
        ]
    )
    return PhysiologicSafetyGateEvent(
        event_id=event_id,
        source_provider=gate_output.source_provider,
        source_path=source_path,
        sha256=event_sha,
        source_gate_sha256=gate_output.sha256,
        observed_at_offset_s=observed_at_offset_s,
        state_candidate=gate_output.state,
        required_action=gate_output.required_action,
        severity=severity,
        ln_transition_candidate=ln_transition,
        eta_delay_minutes=gate_output.eta_delay_minutes,
        route_pressure_review_required=gate_output.route_pressure_effect.route_pressure_review_required,
        dominant_reasons=list(gate_output.dominant_reasons),
        safety_reducer_required=severity in {"rest", "retreat_review", "alert_review"}
        or gate_output.route_pressure_effect.route_pressure_review_required,
        data_quality=gate_output.data_quality.model_dump(mode="json"),
        privacy=gate_output.privacy,
        boundary=ScoutEnergyBoundary(),
    )


def dry_run_physio_reducer(
    events: list[PhysiologicSafetyGateEvent | dict[str, Any]],
    *,
    source_path: str = "inline:physiologic-safety-gate-events",
) -> PhysiologicReducerDryRun:
    event_models = [
        event if isinstance(event, PhysiologicSafetyGateEvent) else PhysiologicSafetyGateEvent.model_validate(event)
        for event in events
    ]
    selected = max(event_models, key=lambda event: _severity_rank(event.severity), default=None)
    recommendation = _recommendation_for_severity(selected.severity if selected else "none")
    ln_candidate = selected.ln_transition_candidate if selected else "none"
    event_refs = [
        {
            "event_id": event.event_id,
            "sha256": event.sha256,
            "state_candidate": event.state_candidate,
            "severity": event.severity,
            "ln_transition_candidate": event.ln_transition_candidate,
            "route_pressure_review_required": event.route_pressure_review_required,
        }
        for event in event_models
    ]
    reducer_sha = aggregate_sha256(
        [
            {
                "source_path": source_path,
                "event_refs": event_refs,
                "selected_event_sha256": selected.sha256 if selected else None,
                "recommendation": recommendation,
                "ln_transition_candidate": ln_candidate,
            }
        ]
    )
    return PhysiologicReducerDryRun(
        source_path=source_path,
        sha256=reducer_sha,
        event_count=len(event_models),
        selected_event_sha256=selected.sha256 if selected else None,
        highest_state_candidate=selected.state_candidate if selected else None,
        highest_severity=selected.severity if selected else "none",
        recommendation=recommendation,
        ln_transition_candidate=ln_candidate,
        route_pressure_review_required=any(event.route_pressure_review_required for event in event_models),
        event_refs=event_refs,
        data_quality=ScoutEnergyDataQuality(
            heart_rate_confidence=_max_confidence(
                [event.data_quality.get("heart_rate_confidence") for event in event_models]
            ),
            gps_confidence=_max_confidence([event.data_quality.get("gps_confidence") for event in event_models]),
            provider_value_confidence=_max_confidence(
                [event.data_quality.get("provider_value_confidence") for event in event_models]
            ),
            limitations=[
                "dry run computes reducer candidate only",
                "actual Phase 1 L_n transition remains owned by Safety Arbiter / State Reducer",
            ],
        ),
        privacy=ScoutEnergyPrivacy(),
        boundary=ScoutEnergyBoundary(),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scout physiologic integration utilities")
    subparsers = parser.add_subparsers(dest="command", required=True)

    review = subparsers.add_parser("health-auto-export-review")
    review.add_argument("--current-zip", required=True)
    review.add_argument("--previous-zip")
    review.add_argument("--output-dir", required=True)
    review.add_argument("--activity-type", choices=["walking", "hiking"], default="walking")
    review.add_argument("--window-minutes", type=int, default=15)

    replay = subparsers.add_parser("sensorlogger-replay")
    replay.add_argument("--sensorlogger-vitals-jsonl", required=True)
    replay.add_argument("--output-dir", required=True)
    replay.add_argument("--route-context-json")
    replay.add_argument("--baseline-json")
    replay.add_argument("--window-minutes", type=int, default=15)
    replay.add_argument("--activity-type", choices=["walking", "hiking", "running", "other"], default="hiking")
    replay.add_argument("--max-records", type=int, default=1000)

    args = parser.parse_args(argv)
    if args.command == "health-auto-export-review":
        result = write_physio_review_from_health_auto_export(
            args.current_zip,
            previous_zip_path=args.previous_zip,
            output_dir=args.output_dir,
            activity_type=args.activity_type,
            window_minutes=args.window_minutes,
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0

    if args.command == "sensorlogger-replay":
        route_context = _load_json(Path(args.route_context_json)) if args.route_context_json else None
        result = run_physio_integration_replay(
            args.sensorlogger_vitals_jsonl,
            output_dir=args.output_dir,
            route_context=route_context,
            baseline_path=args.baseline_json,
            window_minutes=args.window_minutes,
            activity_type=args.activity_type,
            max_records=args.max_records,
        )
        print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, sort_keys=True))
        return 0

    raise AssertionError(f"unhandled command: {args.command}")


def _artifact_index_entry(path: Path, payload: dict[str, Any], *, root: Path) -> PhysiologicArtifactIndexEntry:
    data_quality = payload.get("data_quality") if isinstance(payload.get("data_quality"), dict) else {}
    privacy = payload.get("privacy") if isinstance(payload.get("privacy"), dict) else ScoutEnergyPrivacy().model_dump(mode="json")
    boundary = payload.get("boundary") if isinstance(payload.get("boundary"), dict) else ScoutEnergyBoundary().model_dump(mode="json")
    return PhysiologicArtifactIndexEntry(
        artifact_kind=str(payload.get("artifact_kind", "unknown")),
        artifact_version=payload.get("artifact_version"),
        schema_version=payload.get("schema_version"),
        path=_relpath(path, root),
        sha256=sha256_file(path),
        source_provider=str(payload.get("source_provider", "unknown")),
        source_path=str(payload.get("source_path", _relpath(path, root))),
        source_sha256=payload.get("source_gate_sha256") or payload.get("source_replay_sha256"),
        data_quality=data_quality,
        privacy=privacy,
        boundary=boundary,
        handoff_role=_handoff_role(payload),
    )


def _windows_from_frames(
    frames: list[PhysiologicSensorLoggerFrame],
    *,
    window_minutes: int,
    reference_pace_mps: float | None,
) -> list[PhysiologicActivityWindowSummary]:
    if not frames:
        return []
    window_seconds = window_minutes * 60
    max_elapsed = max(frame.elapsed_s for frame in frames)
    window_count = max(1, math.ceil((max_elapsed + 1) / window_seconds))
    windows: list[PhysiologicActivityWindowSummary] = []
    for window_index in range(1, window_count + 1):
        start_s = (window_index - 1) * window_seconds
        end_s = window_index * window_seconds
        bucket = [frame for frame in frames if start_s <= frame.elapsed_s < end_s]
        if not bucket:
            continue
        duration_min = max(1.0, min(window_seconds, max(frame.elapsed_s for frame in bucket) - start_s + 60) / 60.0)
        distance_m = _window_distance_m(bucket)
        energy_kj = _window_energy_kj(bucket)
        heart_rates = [frame.heart_rate_bpm for frame in bucket if frame.heart_rate_bpm is not None]
        paces = [distance_m / (duration_min * 60.0)] if duration_min > 0 else []
        pace = paces[0] if paces else None
        cadence_values = [frame.cadence_spm for frame in bucket if frame.cadence_spm is not None]
        cadence = float(median(cadence_values)) if cadence_values else None
        avg_hr = float(sum(heart_rates) / len(heart_rates)) if heart_rates else None
        max_hr = max(heart_rates) if heart_rates else None
        p90_hr = _percentile(heart_rates, 0.9) if heart_rates else None
        high_hr_burden = _high_hr_burden(heart_rates, duration_min=duration_min)
        heart_rate_pressure = bool((p90_hr or avg_hr or 0) >= 150)
        movement_efficiency = (
            round(pace / reference_pace_mps, 4)
            if pace is not None and reference_pace_mps and reference_pace_mps > 0
            else None
        )
        high_hr_low_efficiency = bool(
            heart_rate_pressure and movement_efficiency is not None and movement_efficiency <= 0.70
        )
        rest_ratio = _rest_ratio(bucket, window_duration_s=duration_min * 60.0)
        rest_cost = WindowRestCostFeature(
            rest_ratio_recent_window=rest_ratio,
            following_rest_cost_minutes_next_60m=0.0,
            following_rest_window_count=0,
            stage="rest_cost" if rest_ratio >= 0.30 else "watch" if rest_ratio >= 0.15 else "none",
            limitations=["SensorLogger live replay has no future-window rest-cost lookahead"],
        )
        windows.append(
            PhysiologicActivityWindowSummary(
                session_index=1,
                window_index=window_index,
                elapsed_start_min=round(start_s / 60),
                elapsed_end_min=round(end_s / 60),
                duration_min=round(duration_min, 3),
                distance_m=round(distance_m, 3),
                active_energy_kj=round(energy_kj, 3) if energy_kj > 0 else None,
                avg_heart_rate_bpm=round(avg_hr, 3) if avg_hr is not None else None,
                max_heart_rate_bpm=round(max_hr, 3) if max_hr is not None else None,
                p90_heart_rate_bpm=round(p90_hr, 3) if p90_hr is not None else None,
                high_heart_rate_burden=high_hr_burden,
                heart_rate_pressure=heart_rate_pressure,
                pace_mps=round(pace, 4) if pace is not None else None,
                cadence_spm=round(cadence, 3) if cadence is not None else None,
                movement_efficiency_ratio_to_session_reference=movement_efficiency,
                high_hr_low_efficiency_window=high_hr_low_efficiency,
                rest_cost=rest_cost,
            )
        )
    return windows


def _apply_window_reference_ratios(
    windows: list[PhysiologicActivityWindowSummary],
    *,
    reference_pace: float | None,
) -> list[PhysiologicActivityWindowSummary]:
    if not reference_pace or reference_pace <= 0:
        return windows
    updated: list[PhysiologicActivityWindowSummary] = []
    for window in windows:
        efficiency = (
            round(window.pace_mps / reference_pace, 4)
            if window.pace_mps is not None and reference_pace > 0
            else None
        )
        updated.append(
            window.model_copy(
                update={
                    "movement_efficiency_ratio_to_session_reference": efficiency,
                    "high_hr_low_efficiency_window": bool(
                        window.heart_rate_pressure and efficiency is not None and efficiency <= 0.70
                    ),
                }
            )
        )
    return updated


def _window_distance_m(frames: list[PhysiologicSensorLoggerFrame]) -> float:
    deltas = [frame.distance_delta_m for frame in frames if frame.distance_delta_m is not None]
    if deltas:
        return max(0.0, sum(deltas))
    cumulative = [frame.distance_m for frame in frames if frame.distance_m is not None]
    if len(cumulative) >= 2 and max(cumulative) >= min(cumulative):
        return max(0.0, max(cumulative) - min(cumulative))
    if len(cumulative) == 1:
        return max(0.0, cumulative[0])
    return 0.0


def _window_energy_kj(frames: list[PhysiologicSensorLoggerFrame]) -> float:
    deltas = [frame.active_energy_delta_kj for frame in frames if frame.active_energy_delta_kj is not None]
    if deltas:
        return max(0.0, sum(deltas))
    values = [frame.active_energy_kj for frame in frames if frame.active_energy_kj is not None]
    if not values:
        return 0.0
    if len(values) >= 2 and values[-1] >= values[0]:
        return max(0.0, values[-1] - values[0])
    return max(0.0, sum(values))


def _high_hr_burden(heart_rates: list[float], *, duration_min: float) -> HighHeartRateBurden:
    thresholds = [160, 165, 170]
    sample_count = len(heart_rates)
    minutes_per_sample = duration_min / sample_count if sample_count else 0.0
    total_minutes: dict[str, float] = {}
    continuous_minutes: dict[str, float] = {}
    percent_samples: dict[str, float] = {}
    for threshold in thresholds:
        key = str(threshold)
        above = [rate >= threshold for rate in heart_rates]
        total = sum(1 for item in above if item) * minutes_per_sample
        longest = _longest_true_run(above) * minutes_per_sample
        total_minutes[key] = round(total, 3)
        continuous_minutes[key] = round(longest, 3)
        percent_samples[key] = round((sum(1 for item in above if item) / sample_count) if sample_count else 0.0, 4)
    return HighHeartRateBurden(
        thresholds_bpm=thresholds,
        total_minutes_at_or_above=total_minutes,
        continuous_minutes_at_or_above=continuous_minutes,
        percent_samples_at_or_above=percent_samples,
        sample_count=sample_count,
        sample_cadence_s=round(duration_min * 60 / sample_count) if sample_count else None,
    )


def _rest_ratio(frames: list[PhysiologicSensorLoggerFrame], *, window_duration_s: float) -> float:
    if not frames or window_duration_s <= 0:
        return 0.0
    sorted_frames = sorted(frames, key=lambda frame: frame.elapsed_s)
    rest_seconds = 0.0
    for previous, current in zip(sorted_frames, sorted_frames[1:]):
        elapsed_delta = max(0, current.elapsed_s - previous.elapsed_s)
        distance_delta = current.distance_delta_m
        if distance_delta is None and previous.distance_m is not None and current.distance_m is not None:
            distance_delta = max(0.0, current.distance_m - previous.distance_m)
        pace = (distance_delta or 0.0) / elapsed_delta if elapsed_delta > 0 else 0.0
        if pace < 0.15:
            rest_seconds += elapsed_delta
    return round(min(1.0, rest_seconds / window_duration_s), 4)


def _load_baseline_context(
    *,
    baseline_context: PhysiologicBaselineContext | dict[str, Any] | None,
    baseline_path: Path | str | None,
) -> PhysiologicBaselineContext:
    if baseline_context is not None:
        return baseline_context if isinstance(baseline_context, PhysiologicBaselineContext) else PhysiologicBaselineContext.model_validate(baseline_context)
    if baseline_path is None:
        return PhysiologicBaselineContext()
    path = Path(baseline_path).expanduser()
    payload = _load_json(path)
    if "runtime_baseline_context" in payload:
        return PhysiologicBaselineContext.model_validate(payload["runtime_baseline_context"])
    if payload.get("artifact_kind") == "scout_energy_reserve_baseline":
        trend = payload.get("reserve_trend", {})
        stable = payload.get("stable_90_day_baseline", {})
        return PhysiologicBaselineContext(
            personal_envelope_available=True,
            reserve_band=trend.get("current_band"),
            reserve_score=trend.get("reserve_score"),
            stable_baseline_activity_count=int(stable.get("activity_count") or payload.get("activity_count") or 0),
        )
    return PhysiologicBaselineContext.model_validate(payload)


def _route_context(route_context: PhysiologicRouteContext | dict[str, Any] | None) -> PhysiologicRouteContext:
    if route_context is None:
        return PhysiologicRouteContext(
            route_id="runtime_sensorlogger_replay",
            segment_id="current",
            distance_to_next_checkpoint_m=0,
            estimated_minutes_to_next_checkpoint=0,
            estimated_minutes_to_planned_camp=0,
            daylight_buffer_minutes=999,
        )
    return route_context if isinstance(route_context, PhysiologicRouteContext) else PhysiologicRouteContext.model_validate(route_context)


def _severity_for_state(state: PhysiologicGateState) -> tuple[SafetyGateSeverity, LnTransitionCandidate]:
    mapping: dict[str, tuple[SafetyGateSeverity, LnTransitionCandidate]] = {
        "warmup": ("none", "none"),
        "normal": ("none", "none"),
        "watch": ("watch", "candidate_watch"),
        "stop_and_rest": ("rest", "candidate_rest"),
        "retreat_suggested": ("retreat_review", "candidate_retreat"),
        "alert_candidate": ("alert_review", "candidate_alert_review"),
    }
    return mapping[state]


def _recommendation_for_severity(severity: SafetyGateSeverity) -> ReducerRecommendation:
    return {
        "none": "continue_monitoring",
        "watch": "slow_down",
        "rest": "stop_and_rest",
        "retreat_review": "retreat_review",
        "alert_review": "alert_review",
    }[severity]


def _severity_rank(severity: SafetyGateSeverity) -> int:
    return {
        "none": 0,
        "watch": 1,
        "rest": 2,
        "retreat_review": 3,
        "alert_review": 4,
    }[severity]


def _handoff_role(payload: dict[str, Any]) -> str:
    artifact_kind = str(payload.get("artifact_kind", ""))
    if artifact_kind == "scout_physiologic_safety_gate_event":
        return "safety_gate_event"
    if artifact_kind == "scout_physiologic_reducer_dry_run":
        return "reducer_dry_run"
    if artifact_kind == "scout_runtime_physiologic_gate":
        return "gate_evidence"
    if "gate_input" in artifact_kind:
        return "gate_input"
    if "windowed_activity_replay" in artifact_kind:
        return "windowed_replay"
    if "physio_review_capsule" in artifact_kind:
        return "admin_review_capsule"
    return "review_evidence"


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


def _row_value(row: Any, keys: tuple[str, ...]) -> Any:
    if not isinstance(row, dict):
        return None
    for key in keys:
        if key in row:
            value = row[key]
            if isinstance(value, dict) and "qty" in value:
                return value.get("qty")
            return value
    return None


def _first_present_float(values: list[Any]) -> float | None:
    for value in values:
        if value in (None, ""):
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            return number
    return None


def _elapsed_seconds_for_row(row: dict[str, Any], *, frame_index: int, first_timestamp: float | None) -> int:
    offset = _first_present_float(
        [
            _row_value(row, ("elapsed_s", "offset_s", "timestamp_offset_s", "received_at_offset_s")),
            _row_value(row.get("values", {}), ("elapsed_s", "offset_s")),
        ]
    )
    if offset is not None:
        return max(0, round(offset))
    timestamp_value = _first_present_float([_row_value(row, ("timestamp_s", "time_s", "loggingTime", "time"))])
    if timestamp_value is not None and first_timestamp is not None:
        if timestamp_value > 10_000_000_000_000:
            timestamp_value = timestamp_value / 1_000_000_000
        normalized_first = first_timestamp / 1_000_000_000 if first_timestamp > 10_000_000_000_000 else first_timestamp
        return max(0, round(timestamp_value - normalized_first))
    return (frame_index - 1) * 60


def _sample_cadence_seconds(frames: list[PhysiologicSensorLoggerFrame]) -> int | None:
    if len(frames) < 2:
        return None
    deltas = [
        current.elapsed_s - previous.elapsed_s
        for previous, current in zip(frames, frames[1:])
        if current.elapsed_s > previous.elapsed_s
    ]
    return round(float(median(deltas))) if deltas else None


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(len(ordered) * percentile) - 1))
    return float(ordered[index])


def _longest_true_run(values: list[bool]) -> int:
    longest = 0
    current = 0
    for value in values:
        if value:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def _max_confidence(values: list[Any]) -> Literal["high", "medium", "low"]:
    rank = {"low": 0, "medium": 1, "high": 2}
    valid = [str(value) for value in values if str(value) in rank]
    if not valid:
        return "low"
    return max(valid, key=lambda item: rank[item])  # type: ignore[return-value]


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object expected: {path}")
    return payload


def _write_model(path: Path, model: BaseModel) -> None:
    _write_json(path, model.model_dump(mode="json"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _relpath(path: Path | None, root: Path) -> str:
    if path is None:
        return "inline"
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


if __name__ == "__main__":
    raise SystemExit(main())
