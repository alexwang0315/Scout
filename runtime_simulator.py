from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol

from replay_runner import ReplayResult, replay_route
from runtime_debug_log import MemoryRuntimeDebugEventLog, RuntimeDebugAppendResult
from runtime_debug_models import RuntimeDebugEvent, RuntimeDebugEventKind
from safety_models import SafetyLevel


class RuntimeDebugLog(Protocol):
    def try_append(self, event: RuntimeDebugEvent) -> RuntimeDebugAppendResult:
        ...

    def list_events(
        self,
        *,
        kind: RuntimeDebugEventKind | None = None,
        since_sequence: int | None = None,
        limit: int | None = None,
    ) -> list[RuntimeDebugEvent]:
        ...


@dataclass(frozen=True)
class RuntimeDebugReplayResult:
    debug_session_id: str
    safety_level: SafetyLevel
    observations_processed: int
    incident_ids: list[str]
    stored_incident_paths: list[Path]
    debug_events: list[RuntimeDebugEvent]
    append_failures: list[RuntimeDebugAppendResult]


def run_runtime_debug_replay(
    *,
    mission_graph_path: Path | str,
    route_path: Path | str,
    map_context_path: Path | str | None = None,
    risk_rules_path: Path | str | None = None,
    mission_context_path: Path | str | None = None,
    route_progress_config_path: Path | str | None = None,
    incident_store_path: Path | str | None = None,
    debug_log: RuntimeDebugLog | None = None,
    session_id: str | None = None,
) -> RuntimeDebugReplayResult:
    resolved_session_id = session_id or _default_session_id(route_path)
    resolved_mission_id = _mission_id_for(mission_graph_path)
    log = debug_log or MemoryRuntimeDebugEventLog()
    recorder = _RuntimeDebugRecorder(
        log=log,
        session_id=resolved_session_id,
        mission_id=resolved_mission_id,
    )
    recorder.record(
        kind="debug_session_started",
        phase="phase35",
        summary="Runtime debug replay started.",
        payload={
            "mission_graph_path": str(mission_graph_path),
            "route_path": str(route_path),
            "incident_store_enabled": incident_store_path is not None,
        },
    )

    result = replay_route(
        mission_graph_path=mission_graph_path,
        route_path=route_path,
        map_context_path=map_context_path,
        risk_rules_path=risk_rules_path,
        mission_context_path=mission_context_path,
        route_progress_config_path=route_progress_config_path,
        incident_store_path=incident_store_path,
    )
    _record_replay_result(recorder, result)
    recorder.record(
        kind="debug_session_completed",
        phase="phase35",
        summary="Runtime debug replay completed.",
        payload={
            "observations_processed": result.observations_processed,
            "safety_level": result.safety_state.level.value,
            "incident_count": len(result.incident_packages),
            "stored_incident_count": len(result.stored_incident_paths),
        },
    )

    return RuntimeDebugReplayResult(
        debug_session_id=resolved_session_id,
        safety_level=result.safety_state.level,
        observations_processed=result.observations_processed,
        incident_ids=[package.incident_id for package in result.incident_packages],
        stored_incident_paths=list(result.stored_incident_paths),
        debug_events=recorder.events,
        append_failures=recorder.append_failures,
    )


def runtime_debug_replay_summary(result: RuntimeDebugReplayResult) -> dict[str, Any]:
    return {
        "debug_session_id": result.debug_session_id,
        "safety_level": result.safety_level.value,
        "observations_processed": result.observations_processed,
        "incident_ids": result.incident_ids,
        "stored_incident_paths": [str(path) for path in result.stored_incident_paths],
        "debug_event_count": len(result.debug_events),
        "append_failure_count": len(result.append_failures),
    }


def _record_replay_result(recorder: "_RuntimeDebugRecorder", result: ReplayResult) -> None:
    recorder.record(
        kind="observation_ingested",
        phase="phase1",
        subject_ref="observation.gpx_replay",
        summary="Replay observations ingested.",
        payload={"observation_count": result.observations_processed, "source": "gpx_replay"},
    )
    recorder.record(
        kind="route_progress_evaluated",
        phase="phase1",
        subject_ref="route_progress.gpx_replay",
        correlation_refs=["observation.gpx_replay"],
        summary="Route progress evaluated for replay observations.",
        payload={"observation_count": result.observations_processed},
    )

    for profile in sorted({decision.profile.value for decision in result.recording_decisions}):
        recorder.record(
            kind="recording_policy_selected",
            phase="phase1",
            subject_ref=f"recording_policy.profile.{profile}",
            summary="Recording policy profile selected during replay.",
            payload={
                "profile": profile,
                "decision_count": sum(1 for decision in result.recording_decisions if decision.profile.value == profile),
            },
        )

    for arrival in result.checkpoint_hits:
        recorder.record(
            kind="checkpoint_detected",
            phase="phase1",
            subject_ref=f"checkpoint.{arrival.checkpoint.checkpoint_id}",
            summary="Checkpoint detected during replay.",
            payload={
                "checkpoint_id": arrival.checkpoint.checkpoint_id,
                "distance_m": arrival.distance_m,
                "segment_capsule_id": arrival.segment_capsule.capsule_id if arrival.segment_capsule else None,
            },
        )

    for update in result.progress_updates:
        if update.checkpoint is None and update.segment_capsule is None:
            continue
        recorder.record(
            kind="progress_update_recorded",
            phase="phase1",
            subject_ref=(
                f"checkpoint.{update.checkpoint.checkpoint_id}"
                if update.checkpoint is not None
                else update.segment_capsule.capsule_id
            ),
            summary="Mission progress update recorded.",
            payload={
                "checkpoint_id": update.checkpoint.checkpoint_id if update.checkpoint else None,
                "segment_capsule_id": update.segment_capsule.capsule_id if update.segment_capsule else None,
            },
        )

    for event in result.safety_events:
        recorder.record(
            kind="safety_event_emitted",
            phase="phase1",
            subject_ref=f"safety_event.{event.event_type.value}.{event.timestamp}",
            summary="Safety event emitted during replay.",
            payload={
                "event_type": event.event_type.value,
                "safety_level": event.level.value,
                "timestamp": event.timestamp,
                "reason": event.reason,
                "confidence": event.confidence,
            },
        )

    for transition in result.safety_state.transitions:
        recorder.record(
            kind="safety_transition_recorded",
            phase="phase1",
            subject_ref=f"safety_transition.{transition.timestamp}",
            summary="Safety state transition recorded.",
            payload={
                "from_level": transition.from_level.value,
                "to_level": transition.to_level.value,
                "timestamp": transition.timestamp,
                "reason": transition.reason,
            },
        )

    for package in result.incident_packages:
        recorder.record(
            kind="incident_package_created",
            phase="phase1",
            subject_ref=f"incident_package.{package.incident_id}",
            summary="Incident package created.",
            payload={
                "incident_id": package.incident_id,
                "trigger_level": package.trigger_level.value,
                "triggered_at": package.triggered_at,
                "trigger_event_type": package.trigger_event.event_type.value,
            },
        )

    for path in result.stored_incident_paths:
        recorder.record(
            kind="incident_package_persisted",
            phase="phase1",
            subject_ref=f"incident_package.{path.stem}",
            summary="Incident package persisted.",
            payload={"incident_id": path.stem, "path": str(path)},
        )


class _RuntimeDebugRecorder:
    def __init__(self, *, log: RuntimeDebugLog, session_id: str, mission_id: str):
        self.log = log
        self.session_id = session_id
        self.mission_id = mission_id
        self.events: list[RuntimeDebugEvent] = []
        self.append_failures: list[RuntimeDebugAppendResult] = []

    def record(
        self,
        *,
        kind: RuntimeDebugEventKind,
        phase: str,
        summary: str,
        payload: dict[str, Any],
        subject_ref: str | None = None,
        correlation_refs: list[str] | None = None,
        severity: str = "info",
    ) -> RuntimeDebugEvent:
        sequence = len(self.events) + 1
        event = RuntimeDebugEvent(
            event_id=f"debug_event.{_id_token(self.session_id)}.{sequence:06d}",
            session_id=self.session_id,
            mission_id=self.mission_id,
            timestamp=_timestamp_for_sequence(sequence),
            sequence=sequence,
            kind=kind,
            source="runtime_simulator",
            phase=phase,  # type: ignore[arg-type]
            severity=severity,  # type: ignore[arg-type]
            subject_ref=subject_ref,
            correlation_refs=correlation_refs or [],
            summary=summary,
            payload=payload,
        )
        self.events.append(event)
        append_result = self.log.try_append(event)
        if not append_result.succeeded:
            self.append_failures.append(append_result)
        return event


def _default_session_id(route_path: Path | str) -> str:
    return f"debug_session.{Path(route_path).stem}"


def _mission_id_for(mission_graph_path: Path | str) -> str:
    return f"mission.{Path(mission_graph_path).stem}"


def _timestamp_for_sequence(sequence: int) -> str:
    timestamp = datetime(2026, 5, 18, tzinfo=timezone.utc) + timedelta(seconds=sequence)
    return timestamp.isoformat().replace("+00:00", "Z")


def _id_token(value: str) -> str:
    return "".join(character if character.isalnum() else "_" for character in value)
