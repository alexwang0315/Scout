from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from pydantic import BaseModel, ConfigDict, Field

from runtime_debug_log import FileRuntimeDebugEventLog
from runtime_debug_models import RuntimeDebugEvent


class Phase46DebugProjectorModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Phase46DebugProjectorSummary(Phase46DebugProjectorModel):
    artifact_kind: str = "phase46_live_replay_debug_projector_summary"
    status: str
    output_jsonl_path: str
    event_count: int = Field(ge=0)
    stream_status_url: str
    runtime_status_url: str
    session_id: str
    mission_id: str
    accepted_delta: int = Field(ge=0)
    observations_delta: int = Field(ge=0)
    incident_delta: int = Field(ge=0)
    final_safety_level: str | None = None
    final_stream_control_status: str | None = None
    boundary: dict[str, bool]

    def to_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True
        ) + "\n"


def project_phase46_live_replay_debug_events(
    *,
    stream_snapshots: list[dict[str, Any]],
    runtime_snapshots: list[dict[str, Any]],
    output_jsonl_path: Path | str,
    session_id: str = "debug_session.phase46_live_replay",
    mission_id: str = "mission.normal_climb",
    stream_status_url: str = "http://scout.local:9099/runtime/streams/status",
    runtime_status_url: str = "http://scout.local:9099/runtime/status",
    replace: bool = False,
) -> Phase46DebugProjectorSummary:
    if len(stream_snapshots) != len(runtime_snapshots):
        raise ValueError("stream_snapshots and runtime_snapshots must have the same length")
    if not stream_snapshots:
        raise ValueError("at least one snapshot pair is required")

    output_path = Path(output_jsonl_path)
    if replace and output_path.exists():
        output_path.unlink()
    event_log = FileRuntimeDebugEventLog(output_path)
    events = _events_from_snapshots(
        stream_snapshots=stream_snapshots,
        runtime_snapshots=runtime_snapshots,
        session_id=session_id,
        mission_id=mission_id,
    )
    for event in events:
        event_log.append(event)

    first_stream = _http_surface(stream_snapshots[0])
    last_stream = _http_surface(stream_snapshots[-1])
    first_runtime = runtime_snapshots[0]
    last_runtime = runtime_snapshots[-1]
    return Phase46DebugProjectorSummary(
        status="debug_events_projected",
        output_jsonl_path=str(output_path),
        event_count=len(events),
        stream_status_url=stream_status_url,
        runtime_status_url=runtime_status_url,
        session_id=session_id,
        mission_id=mission_id,
        accepted_delta=_delta(last_stream, first_stream, "accepted_count"),
        observations_delta=_delta(last_runtime, first_runtime, "observations_processed"),
        incident_delta=_delta(last_runtime, first_runtime, "stored_incidents"),
        final_safety_level=last_runtime.get("safety_level"),
        final_stream_control_status=_control_status(stream_snapshots[-1]),
        boundary=_boundary(),
    )


def run_phase46_live_replay_debug_projector(
    *,
    stream_status_url: str,
    runtime_status_url: str,
    output_jsonl_path: Path | str,
    session_id: str,
    mission_id: str,
    poll_count: int,
    interval_seconds: float,
    timeout_seconds: float,
    replace: bool,
) -> Phase46DebugProjectorSummary:
    if poll_count < 1:
        raise ValueError("poll_count must be at least 1")

    output_path = Path(output_jsonl_path)
    if replace and output_path.exists():
        output_path.unlink()
    event_log = FileRuntimeDebugEventLog(output_path)
    baseline_stream_snapshot = _fetch_json(stream_status_url, timeout_seconds=timeout_seconds)
    baseline_runtime_snapshot = _fetch_json(runtime_status_url, timeout_seconds=timeout_seconds)
    previous_stream_snapshot = baseline_stream_snapshot
    previous_runtime_snapshot = baseline_runtime_snapshot
    final_stream_snapshot = baseline_stream_snapshot
    final_runtime_snapshot = baseline_runtime_snapshot
    sequence = 1
    event_count = 0

    event_log.append(
        _start_event(
            sequence,
            stream_snapshot=baseline_stream_snapshot,
            runtime_snapshot=baseline_runtime_snapshot,
            session_id=session_id,
            mission_id=mission_id,
        )
    )
    event_count += 1
    sequence += 1

    for index in range(1, poll_count):
        if interval_seconds > 0:
            time.sleep(interval_seconds)
        current_stream_snapshot = _fetch_json(stream_status_url, timeout_seconds=timeout_seconds)
        current_runtime_snapshot = _fetch_json(runtime_status_url, timeout_seconds=timeout_seconds)
        transition_events = _transition_events(
            sequence,
            previous_stream_snapshot=previous_stream_snapshot,
            previous_runtime_snapshot=previous_runtime_snapshot,
            current_stream_snapshot=current_stream_snapshot,
            current_runtime_snapshot=current_runtime_snapshot,
            session_id=session_id,
            mission_id=mission_id,
        )
        for event in transition_events:
            event_log.append(event)
        sequence += len(transition_events)
        event_count += len(transition_events)
        previous_stream_snapshot = current_stream_snapshot
        previous_runtime_snapshot = current_runtime_snapshot
        final_stream_snapshot = current_stream_snapshot
        final_runtime_snapshot = current_runtime_snapshot

    event_log.append(
        _completed_event(
            sequence,
            stream_snapshot=final_stream_snapshot,
            runtime_snapshot=final_runtime_snapshot,
            session_id=session_id,
            mission_id=mission_id,
        )
    )
    event_count += 1

    baseline_stream = _http_surface(baseline_stream_snapshot)
    final_stream = _http_surface(final_stream_snapshot)
    return Phase46DebugProjectorSummary(
        status="debug_events_projected",
        output_jsonl_path=str(output_path),
        event_count=event_count,
        stream_status_url=stream_status_url,
        runtime_status_url=runtime_status_url,
        session_id=session_id,
        mission_id=mission_id,
        accepted_delta=_delta(final_stream, baseline_stream, "accepted_count"),
        observations_delta=_delta(
            final_runtime_snapshot,
            baseline_runtime_snapshot,
            "observations_processed",
        ),
        incident_delta=_delta(final_runtime_snapshot, baseline_runtime_snapshot, "stored_incidents"),
        final_safety_level=final_runtime_snapshot.get("safety_level"),
        final_stream_control_status=_control_status(final_stream_snapshot),
        boundary=_boundary(),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Project live replay stream/runtime status into sanitized /admin/debug JSONL events."
        )
    )
    parser.add_argument("--stream-status-url", default="http://scout.local:9099/runtime/streams/status")
    parser.add_argument("--runtime-status-url", default="http://scout.local:9099/runtime/status")
    parser.add_argument("--output-jsonl", required=True)
    parser.add_argument("--session-id", default="debug_session.phase46_live_replay")
    parser.add_argument("--mission-id", default="mission.normal_climb")
    parser.add_argument("--poll-count", type=int, default=2)
    parser.add_argument("--interval-seconds", type=float, default=1.0)
    parser.add_argument("--timeout-seconds", type=float, default=5.0)
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--summary-output")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    summary = run_phase46_live_replay_debug_projector(
        stream_status_url=args.stream_status_url,
        runtime_status_url=args.runtime_status_url,
        output_jsonl_path=args.output_jsonl,
        session_id=args.session_id,
        mission_id=args.mission_id,
        poll_count=args.poll_count,
        interval_seconds=args.interval_seconds,
        timeout_seconds=args.timeout_seconds,
        replace=args.replace,
    )
    if args.summary_output:
        Path(args.summary_output).write_text(summary.to_json(), encoding="utf-8")
    else:
        sys.stdout.write(summary.to_json())
    return 0


def _events_from_snapshots(
    *,
    stream_snapshots: list[dict[str, Any]],
    runtime_snapshots: list[dict[str, Any]],
    session_id: str,
    mission_id: str,
) -> list[RuntimeDebugEvent]:
    events: list[RuntimeDebugEvent] = []
    sequence = 1
    baseline_runtime = runtime_snapshots[0]
    events.append(
        _start_event(
            sequence,
            stream_snapshot=stream_snapshots[0],
            runtime_snapshot=baseline_runtime,
            session_id=session_id,
            mission_id=mission_id,
        )
    )
    sequence += 1

    previous_stream_snapshot = stream_snapshots[0]
    previous_runtime = baseline_runtime
    for stream_snapshot, runtime_snapshot in zip(stream_snapshots[1:], runtime_snapshots[1:]):
        transition_events = _transition_events(
            sequence,
            previous_stream_snapshot=previous_stream_snapshot,
            previous_runtime_snapshot=previous_runtime,
            current_stream_snapshot=stream_snapshot,
            current_runtime_snapshot=runtime_snapshot,
            session_id=session_id,
            mission_id=mission_id,
        )
        events.extend(transition_events)
        sequence += len(transition_events)
        previous_stream_snapshot = stream_snapshot
        previous_runtime = runtime_snapshot

    final_runtime = runtime_snapshots[-1]
    events.append(
        _completed_event(
            sequence,
            stream_snapshot=stream_snapshots[-1],
            runtime_snapshot=final_runtime,
            session_id=session_id,
            mission_id=mission_id,
        )
    )
    return events


def _start_event(
    sequence: int,
    *,
    stream_snapshot: dict[str, Any],
    runtime_snapshot: dict[str, Any],
    session_id: str,
    mission_id: str,
) -> RuntimeDebugEvent:
    baseline_stream = _http_surface(stream_snapshot)
    return _event(
        sequence,
        session_id=session_id,
        mission_id=mission_id,
        kind="debug_session_started",
        subject_ref="phase46.live_replay",
        summary="Phase 4.6 live replay debug projection started.",
        payload={
            "runtime_profile": runtime_snapshot.get("runtime_profile"),
            "http_accepted_count": baseline_stream.get("accepted_count"),
            "observations_processed": runtime_snapshot.get("observations_processed"),
            "stored_incidents": runtime_snapshot.get("stored_incidents"),
            "safety_level": runtime_snapshot.get("safety_level"),
            "stream_control_status": _control_status(stream_snapshot),
            "milestone": "phase4.6",
            "boundary": _boundary(),
        },
    )


def _transition_events(
    sequence: int,
    *,
    previous_stream_snapshot: dict[str, Any],
    previous_runtime_snapshot: dict[str, Any],
    current_stream_snapshot: dict[str, Any],
    current_runtime_snapshot: dict[str, Any],
    session_id: str,
    mission_id: str,
) -> list[RuntimeDebugEvent]:
    current_stream = _http_surface(current_stream_snapshot)
    previous_stream = _http_surface(previous_stream_snapshot)
    accepted_delta = _delta(current_stream, previous_stream, "accepted_count")
    observations_delta = _delta(
        current_runtime_snapshot,
        previous_runtime_snapshot,
        "observations_processed",
    )
    incident_delta = _delta(
        current_runtime_snapshot,
        previous_runtime_snapshot,
        "stored_incidents",
    )
    events: list[RuntimeDebugEvent] = []
    if accepted_delta > 0:
        events.append(
            _event(
                sequence,
                session_id=session_id,
                mission_id=mission_id,
                kind="observation_ingested",
                subject_ref=str(current_stream.get("last_device_id") or "runtime_stream.http_push"),
                summary=f"Runtime stream accepted {accepted_delta} replay observation(s).",
                payload={
                    "accepted_delta": accepted_delta,
                    "accepted_count": current_stream.get("accepted_count"),
                    "last_sequence_no": current_stream.get("last_sequence_no"),
                    "last_device_id": current_stream.get("last_device_id"),
                    "last_source_id": current_stream.get("last_source_id"),
                    "last_payload_sha256": current_stream.get("last_payload_sha256"),
                    "last_admission_status": current_stream.get("last_admission_status"),
                    "transport": "http_push",
                    "milestone": "phase4.6",
                    "boundary": _boundary(),
                },
            )
        )
        sequence += 1
    if observations_delta > 0:
        events.append(
            _event(
                sequence,
                session_id=session_id,
                mission_id=mission_id,
                kind="route_progress_evaluated",
                subject_ref="runtime.status",
                summary=f"Runtime processed {observations_delta} replay observation(s).",
                payload={
                    "observations_delta": observations_delta,
                    "observations_processed": current_runtime_snapshot.get("observations_processed"),
                    "checkpoint_hits": current_runtime_snapshot.get("checkpoint_hits"),
                    "stored_incidents": current_runtime_snapshot.get("stored_incidents"),
                    "incident_delta": incident_delta,
                    "safety_level": current_runtime_snapshot.get("safety_level"),
                    "stream_control_status": _control_status(current_stream_snapshot),
                    "milestone": "phase4.6",
                    "boundary": _boundary(),
                },
            )
        )
        sequence += 1
    if incident_delta > 0:
        events.append(
            _event(
                sequence,
                session_id=session_id,
                mission_id=mission_id,
                kind="safety_event_emitted",
                severity="warning",
                subject_ref="runtime.incident_delta",
                summary=f"Runtime stored incident count increased by {incident_delta}.",
                payload={
                    "incident_delta": incident_delta,
                    "stored_incidents": current_runtime_snapshot.get("stored_incidents"),
                    "safety_level": current_runtime_snapshot.get("safety_level"),
                    "milestone": "phase4.6",
                    "boundary": _boundary(),
                },
            )
        )
    return events


def _completed_event(
    sequence: int,
    *,
    stream_snapshot: dict[str, Any],
    runtime_snapshot: dict[str, Any],
    session_id: str,
    mission_id: str,
) -> RuntimeDebugEvent:
    final_stream = _http_surface(stream_snapshot)
    return _event(
        sequence,
        session_id=session_id,
        mission_id=mission_id,
        kind="debug_session_completed",
        subject_ref="phase46.live_replay",
        summary="Phase 4.6 live replay debug projection completed.",
        payload={
            "http_accepted_count": final_stream.get("accepted_count"),
            "observations_processed": runtime_snapshot.get("observations_processed"),
            "stored_incidents": runtime_snapshot.get("stored_incidents"),
            "safety_level": runtime_snapshot.get("safety_level"),
            "stream_control_status": _control_status(stream_snapshot),
            "message_count": 0,
            "phase1_mutation_by_debug": False,
            "observed_fact_written": False,
            "milestone": "phase4.6",
            "boundary": _boundary(),
        },
    )


def _event(
    sequence: int,
    *,
    session_id: str,
    mission_id: str,
    kind: str,
    summary: str,
    subject_ref: str | None = None,
    severity: str = "info",
    payload: dict[str, Any] | None = None,
) -> RuntimeDebugEvent:
    return RuntimeDebugEvent(
        event_id=f"debug_event.phase46_live_replay.{sequence:06d}",
        session_id=session_id,
        mission_id=mission_id,
        timestamp=datetime.now(timezone.utc).isoformat(),
        sequence=sequence,
        kind=kind,
        source="phase46_live_replay_debug_projector",
        phase="phase35",
        severity=severity,
        subject_ref=subject_ref,
        summary=summary,
        payload=dict(payload or {}),
    )


def _fetch_json(url: str, *, timeout_seconds: float) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout_seconds) as response:
        return json.loads(response.read().decode("utf-8"))


def _http_surface(stream_snapshot: dict[str, Any]) -> dict[str, Any]:
    surfaces = stream_snapshot.get("transport_surfaces")
    if not isinstance(surfaces, dict):
        return {}
    surface = surfaces.get("http_push")
    return surface if isinstance(surface, dict) else {}


def _control_status(stream_snapshot: dict[str, Any]) -> str | None:
    control = stream_snapshot.get("control")
    if not isinstance(control, dict):
        return None
    status = control.get("status")
    return status if isinstance(status, str) else None


def _delta(current: dict[str, Any], previous: dict[str, Any], key: str) -> int:
    return max(0, int(current.get(key) or 0) - int(previous.get(key) or 0))


def _boundary() -> dict[str, bool]:
    return {
        "read_only_projection": True,
        "raw_payload_embedded": False,
        "secret_value_embedded": False,
        "runtime_mutation_allowed": False,
        "stream_control_mutation_performed": False,
        "remote_provider_send_performed": False,
        "hardware_control_performed": False,
        "phase2_writeback_performed": False,
        "automatic_sos_sent": False,
        "sms_sent": False,
        "satellite_sent": False,
    }


if __name__ == "__main__":
    raise SystemExit(main())
