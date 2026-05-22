from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from runtime_debug_models import RuntimeDebugEvent
from voice_cue_models import VoiceCue, VoiceCueBoundary


VoiceCueTransportState = Literal["queued", "rendered", "played", "failed"]
VoiceCueEngine = Literal["piper", "espeak", "mock"]


class _RuntimeDebugLog(Protocol):
    def append(self, event: RuntimeDebugEvent) -> RuntimeDebugEvent:
        ...


class MockVoiceTransportRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cue_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    engine: VoiceCueEngine
    priority: str = Field(min_length=1)
    category: str = Field(min_length=1)
    audio_file: str | None = None
    queued_at: str = Field(min_length=1)
    rendered_at: str | None = None
    played_at: str | None = None
    failed_at: str | None = None
    state: VoiceCueTransportState
    source_event_refs: list[str] = Field(default_factory=list)
    failure_reason: str | None = None
    boundary: VoiceCueBoundary = Field(default_factory=VoiceCueBoundary)


class MockVoiceTransport:
    def __init__(
        self,
        *,
        output_jsonl: Path | str | None = None,
        debug_log: _RuntimeDebugLog | None = None,
        session_id: str = "voice_cue_session.local",
        mission_id: str | None = None,
        timestamp_factory: Callable[[], str] | None = None,
    ):
        self.output_jsonl = Path(output_jsonl) if output_jsonl is not None else None
        self.debug_log = debug_log
        self.session_id = session_id
        self.mission_id = mission_id
        self.timestamp_factory = timestamp_factory or _utc_now
        self._records: dict[str, MockVoiceTransportRecord] = {}
        self._event_sequence = 0

    def queue_voice_cue(
        self,
        cue: VoiceCue,
        *,
        engine: VoiceCueEngine = "piper",
        audio_file: str | None = None,
    ) -> MockVoiceTransportRecord:
        timestamp = self.timestamp_factory()
        record = MockVoiceTransportRecord(
            cue_id=cue.cue_id,
            text=cue.text_zh,
            engine=engine,
            priority=cue.priority,
            category=cue.category,
            audio_file=audio_file,
            queued_at=timestamp,
            state="queued",
            source_event_refs=list(cue.source_event_refs),
            boundary=cue.boundary,
        )
        self._records[cue.cue_id] = record
        self._append(record)
        self._append_debug_event(
            kind="voice_cue_queued",
            record=record,
            timestamp=timestamp,
        )
        return record

    def mark_rendered(
        self,
        cue_id: str,
        *,
        engine: VoiceCueEngine | None = None,
        audio_file: str | None = None,
    ) -> MockVoiceTransportRecord:
        current = self._records[cue_id]
        record = current.model_copy(
            update={
                "engine": engine or current.engine,
                "audio_file": audio_file if audio_file is not None else current.audio_file,
                "rendered_at": self.timestamp_factory(),
                "state": "rendered",
                "failure_reason": None,
            }
        )
        self._records[cue_id] = record
        self._append(record)
        self._append_debug_event(
            kind="voice_cue_state_changed",
            record=record,
            timestamp=record.rendered_at or self.timestamp_factory(),
        )
        return record

    def mark_played(self, cue_id: str) -> MockVoiceTransportRecord:
        current = self._records[cue_id]
        record = current.model_copy(
            update={
                "played_at": self.timestamp_factory(),
                "state": "played",
                "failure_reason": None,
            }
        )
        self._records[cue_id] = record
        self._append(record)
        self._append_debug_event(
            kind="voice_cue_state_changed",
            record=record,
            timestamp=record.played_at or self.timestamp_factory(),
        )
        return record

    def mark_failed(self, cue_id: str, *, reason: str) -> MockVoiceTransportRecord:
        current = self._records[cue_id]
        record = current.model_copy(
            update={
                "failed_at": self.timestamp_factory(),
                "state": "failed",
                "failure_reason": reason,
            }
        )
        self._records[cue_id] = record
        self._append(record)
        self._append_debug_event(
            kind="voice_cue_state_changed",
            record=record,
            timestamp=record.failed_at or self.timestamp_factory(),
        )
        return record

    def list_records(self) -> list[MockVoiceTransportRecord]:
        return list(self._records.values())

    def get_record(self, cue_id: str) -> MockVoiceTransportRecord:
        return self._records[cue_id]

    def _append(self, record: MockVoiceTransportRecord) -> None:
        if self.output_jsonl is None:
            return
        self.output_jsonl.parent.mkdir(parents=True, exist_ok=True)
        with self.output_jsonl.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(record.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
                + "\n"
            )

    def _append_debug_event(
        self,
        *,
        kind: Literal["voice_cue_queued", "voice_cue_state_changed"],
        record: MockVoiceTransportRecord,
        timestamp: str,
    ) -> None:
        if self.debug_log is None:
            return
        self._event_sequence += 1
        payload = {
            "cue_id": record.cue_id,
            "text": record.text,
            "engine": record.engine,
            "priority": record.priority,
            "category": record.category,
            "audio_file": record.audio_file,
            "queued_at": record.queued_at,
            "rendered_at": record.rendered_at,
            "played_at": record.played_at,
            "failed_at": record.failed_at,
            "state": record.state,
            "source_event_refs": list(record.source_event_refs),
            "failure_reason": record.failure_reason,
            "boundary": record.boundary.model_dump(mode="json"),
        }
        event = RuntimeDebugEvent(
            event_id=f"debug_event.mock_voice.{self._event_sequence:06d}",
            session_id=self.session_id,
            mission_id=self.mission_id,
            timestamp=timestamp,
            sequence=self._event_sequence,
            kind=kind,
            source="mock_voice_transport",
            phase="phase35",
            severity="error" if record.state == "failed" else "info",
            subject_ref=record.cue_id,
            correlation_refs=list(record.source_event_refs),
            summary=f"Mock voice cue {record.state}.",
            payload=payload,
        )
        if hasattr(self.debug_log, "try_append"):
            self.debug_log.try_append(event)
            return
        self.debug_log.append(event)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
