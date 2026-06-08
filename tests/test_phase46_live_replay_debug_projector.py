from __future__ import annotations

import json
from pathlib import Path

from debug_api import create_debug_app
from fastapi.testclient import TestClient
from phase46_live_replay_debug_projector import (
    project_phase46_live_replay_debug_events,
    run_phase46_live_replay_debug_projector,
)


def test_projector_writes_sanitized_debug_events_for_admin_debug(tmp_path: Path) -> None:
    output_jsonl = tmp_path / "phase46-replay-live.jsonl"

    summary = project_phase46_live_replay_debug_events(
        stream_snapshots=[_stream_snapshot(accepted=5), _stream_snapshot(accepted=7)],
        runtime_snapshots=[
            _runtime_snapshot(observations=10, incidents=2),
            _runtime_snapshot(observations=12, incidents=2),
        ],
        output_jsonl_path=output_jsonl,
        session_id="debug_session.phase46.test",
        mission_id="mission.normal_climb",
        replace=True,
    )
    serialized = output_jsonl.read_text(encoding="utf-8")
    events = [json.loads(line) for line in serialized.splitlines()]

    assert summary.status == "debug_events_projected"
    assert summary.event_count == 4
    assert summary.accepted_delta == 2
    assert summary.observations_delta == 2
    assert summary.incident_delta == 0
    assert [event["kind"] for event in events] == [
        "debug_session_started",
        "observation_ingested",
        "route_progress_evaluated",
        "debug_session_completed",
    ]
    assert events[1]["payload"]["last_payload_sha256"] == "a" * 64
    assert events[1]["payload"]["boundary"]["raw_payload_embedded"] is False
    assert "locationLatitude" not in serialized
    assert "locationLongitude" not in serialized
    assert "runtime-stream-secret-value" not in serialized


def test_projected_events_feed_debug_events_state_and_messages(tmp_path: Path) -> None:
    output_jsonl = tmp_path / "phase46-replay-live.jsonl"
    project_phase46_live_replay_debug_events(
        stream_snapshots=[_stream_snapshot(accepted=5), _stream_snapshot(accepted=6)],
        runtime_snapshots=[
            _runtime_snapshot(observations=10, incidents=2),
            _runtime_snapshot(observations=11, incidents=3, safety_level="L2_CONCERN"),
        ],
        output_jsonl_path=output_jsonl,
        session_id="debug_session.phase46.test",
        mission_id="mission.normal_climb",
        replace=True,
    )
    client = TestClient(create_debug_app(debug_log=_FileLog(output_jsonl)))

    events = client.get("/debug/events").json()
    state = client.get("/debug/state").json()
    messages = client.get("/debug/messages").json()

    assert events["debug_boundary"]["read_only"] is True
    assert [event["kind"] for event in events["events"]][-2:] == [
        "safety_event_emitted",
        "debug_session_completed",
    ]
    assert state["debug_session_id"] == "debug_session.phase46.test"
    assert state["observations_processed"] == 11
    assert state["safety_level"] == "L2_CONCERN"
    assert state["message_count"] == 0
    assert messages["messages"] == []


def test_cli_runner_projects_events_from_live_status_urls(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import phase46_live_replay_debug_projector as projector

    output_jsonl = tmp_path / "phase46-replay-live.jsonl"
    responses = [
        _stream_snapshot(accepted=5),
        _runtime_snapshot(observations=10, incidents=2),
        _stream_snapshot(accepted=6),
        _runtime_snapshot(observations=11, incidents=2),
    ]

    def fake_fetch_json(url: str, *, timeout_seconds: float) -> dict:
        return responses.pop(0)

    monkeypatch.setattr(projector, "_fetch_json", fake_fetch_json)

    summary = run_phase46_live_replay_debug_projector(
        stream_status_url="http://scout.local:9099/runtime/streams/status",
        runtime_status_url="http://scout.local:9099/runtime/status",
        output_jsonl_path=output_jsonl,
        session_id="debug_session.phase46.runner",
        mission_id="mission.normal_climb",
        poll_count=2,
        interval_seconds=0,
        timeout_seconds=5,
        replace=True,
    )
    events = [json.loads(line) for line in output_jsonl.read_text().splitlines()]

    assert responses == []
    assert summary.event_count == 4
    assert summary.accepted_delta == 1
    assert events[0]["kind"] == "debug_session_started"
    assert events[1]["kind"] == "observation_ingested"
    assert events[2]["kind"] == "route_progress_evaluated"
    assert events[3]["kind"] == "debug_session_completed"


class _FileLog:
    def __init__(self, path: Path):
        from runtime_debug_log import FileRuntimeDebugEventLog

        self._log = FileRuntimeDebugEventLog(path)

    def list_events(self, **kwargs):
        return self._log.list_events(**kwargs)


def _stream_snapshot(*, accepted: int) -> dict:
    return {
        "transport_surfaces": {
            "http_push": {
                "accepted_count": accepted,
                "last_sequence_no": accepted,
                "last_device_id": "watch.replay.normal_climb_corridor",
                "last_source_id": "runtime_source.apple_watch.v0",
                "last_payload_sha256": "a" * 64,
                "last_admission_status": "admitted_not_forwarded",
            }
        },
        "control": {"status": "observing"},
    }


def _runtime_snapshot(
    *,
    observations: int,
    incidents: int,
    safety_level: str = "L0_NORMAL",
) -> dict:
    return {
        "runtime_profile": "pi-field-live",
        "observations_processed": observations,
        "stored_incidents": incidents,
        "safety_level": safety_level,
        "checkpoint_hits": 5,
    }
