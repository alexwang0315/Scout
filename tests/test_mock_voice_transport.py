from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from mock_voice_transport import MockVoiceTransport
from runtime_debug_log import MemoryRuntimeDebugEventLog
from voice_cue_models import VoiceCue


def test_mock_voice_transport_records_queue_render_play_jsonl(tmp_path) -> None:
    output_path = tmp_path / "voice_cues.jsonl"
    timestamps = iter(
        [
            "2026-05-21T10:00:00Z",
            "2026-05-21T10:00:01Z",
            "2026-05-21T10:00:02Z",
        ]
    )
    transport = MockVoiceTransport(
        output_jsonl=output_path,
        timestamp_factory=lambda: next(timestamps),
    )
    cue = _cue()

    queued = transport.queue_voice_cue(cue, engine="piper")
    rendered = transport.mark_rendered(cue.cue_id, audio_file="/tmp/scout.wav")
    played = transport.mark_played(cue.cue_id)

    assert queued.state == "queued"
    assert rendered.state == "rendered"
    assert rendered.audio_file == "/tmp/scout.wav"
    assert played.state == "played"
    assert played.played_at == "2026-05-21T10:00:02Z"
    assert played.boundary.safety_decision_change_allowed is False
    assert played.boundary.remote_outbound_allowed is False
    assert played.boundary.hardware_control_allowed is False

    lines = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines()]
    assert [line["state"] for line in lines] == ["queued", "rendered", "played"]
    assert all(line["cue_id"] == cue.cue_id for line in lines)
    assert all(line["text"] == cue.text_zh for line in lines)
    assert all(line["engine"] == "piper" for line in lines)
    assert all(line["priority"] == "warning" for line in lines)
    assert all(line["category"] == "route" for line in lines)
    assert all(line["source_event_refs"] == ["debug_event.route.1"] for line in lines)
    assert all(line["boundary"]["remote_outbound_allowed"] is False for line in lines)


def test_mock_voice_transport_records_failure_without_playing_audio(tmp_path) -> None:
    output_path = tmp_path / "voice_cues.jsonl"
    timestamps = iter(["2026-05-21T10:00:00Z", "2026-05-21T10:00:01Z"])
    transport = MockVoiceTransport(
        output_jsonl=output_path,
        timestamp_factory=lambda: next(timestamps),
    )
    cue = _cue(cue_id="voice_cue.device.000001", text_zh="裝置音訊輸出失敗。")

    transport.queue_voice_cue(cue, engine="espeak")
    failed = transport.mark_failed(cue.cue_id, reason="mock renderer unavailable")

    assert failed.state == "failed"
    assert failed.engine == "espeak"
    assert failed.failure_reason == "mock renderer unavailable"
    assert failed.played_at is None


def test_mock_voice_transport_rejects_invalid_transition_timestamp(tmp_path) -> None:
    output_path = tmp_path / "voice_cues.jsonl"
    timestamps = iter(["2026-05-21T10:00:00Z", "not-a-time"])
    transport = MockVoiceTransport(
        output_jsonl=output_path,
        timestamp_factory=lambda: next(timestamps),
    )
    cue = _cue()

    transport.queue_voice_cue(cue, engine="mock")

    with pytest.raises(ValidationError):
        transport.mark_played(cue.cue_id)


def test_mock_voice_transport_optionally_records_runtime_debug_events() -> None:
    log = MemoryRuntimeDebugEventLog()
    timestamps = iter(
        [
            "2026-05-21T10:00:00Z",
            "2026-05-21T10:00:01Z",
            "2026-05-21T10:00:02Z",
        ]
    )
    transport = MockVoiceTransport(
        debug_log=log,
        session_id="debug_session.voice.20260521T100000Z",
        mission_id="mission.normal_climb",
        timestamp_factory=lambda: next(timestamps),
    )
    cue = _cue()

    transport.queue_voice_cue(cue, engine="piper")
    transport.mark_rendered(cue.cue_id, audio_file="/tmp/scout.wav")
    transport.mark_failed(cue.cue_id, reason="mock renderer unavailable")

    events = log.list_events()
    assert [event.kind for event in events] == [
        "voice_cue_queued",
        "voice_cue_state_changed",
        "voice_cue_state_changed",
    ]
    assert [event.payload["state"] for event in events] == ["queued", "rendered", "failed"]
    assert events[0].source == "mock_voice_transport"
    assert events[0].phase == "phase35"
    assert events[0].subject_ref == cue.cue_id
    assert events[0].correlation_refs == ["debug_event.route.1"]
    assert events[0].payload["engine"] == "piper"
    assert events[0].payload["priority"] == "warning"
    assert events[0].payload["category"] == "route"
    assert events[0].payload["boundary"]["safety_decision_change_allowed"] is False
    assert events[0].payload["boundary"]["remote_outbound_allowed"] is False
    assert events[0].payload["boundary"]["hardware_control_allowed"] is False
    assert events[-1].severity == "error"
    assert events[-1].payload["failure_reason"] == "mock renderer unavailable"


def test_mock_voice_transport_has_no_real_audio_or_network_imports() -> None:
    source = Path("mock_voice_transport.py").read_text(encoding="utf-8")

    for forbidden in ("subprocess", "pyaudio", "sounddevice", "requests", "httpx", "bluetooth"):
        assert forbidden not in source


def _cue(
    *,
    cue_id: str = "voice_cue.route.000001",
    text_zh: str = "偏離路線，請停下確認方向。",
) -> VoiceCue:
    return VoiceCue(
        cue_id=cue_id,
        priority="warning",
        category="route",
        text_zh=text_zh,
        source_event_refs=["debug_event.route.1"],
        confidence=0.9,
    )
