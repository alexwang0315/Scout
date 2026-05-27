from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from mock_outbound_transport import MockOutboundMessage, MockOutboundTransport
from mock_voice_transport import MockVoiceTransport, MockVoiceTransportRecord
from runtime_debug_log import FileRuntimeDebugEventLog, MemoryRuntimeDebugEventLog
from runtime_debug_models import RuntimeDebugEvent
from voice_cue_models import VoiceCue, VoiceCueRepeatPolicy


ActivationSource = Literal["physical_sos", "explicit_sos_command", "operator_test"]


class ScoutSosPlaybookModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ScoutSosActivationEvent(ScoutSosPlaybookModel):
    sos_event_id: str = Field(min_length=1)
    activation_source: ActivationSource
    activated_at: str = Field(min_length=1)
    trip_id: str = Field(min_length=1)
    client_id: str | None = None
    scout_machine_id: str | None = None
    position: dict[str, Any] | None = None
    message_zh: str | None = None
    source_refs: list[str] = Field(default_factory=list)

    @field_validator("activated_at")
    @classmethod
    def validate_activated_at(cls, value: str) -> str:
        from datetime import datetime

        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value


class ScoutSosPlaybookBoundary(ScoutSosPlaybookModel):
    sos_delegated_emergency: Literal[True] = True
    deterministic_playbook: Literal[True] = True
    mock_outbound_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False
    live_safety_api_calls_allowed: Literal[False] = False
    phase1_safety_mutation_allowed: Literal[False] = False
    real_sos_sent: Literal[False] = False
    real_sms_sent: Literal[False] = False
    real_satellite_sent: Literal[False] = False
    remote_outbound_send_allowed: Literal[False] = False
    hardware_control_allowed: Literal[False] = False


class ScoutSosPlaybookStep(ScoutSosPlaybookModel):
    step_id: str = Field(min_length=1)
    status: Literal["planned", "completed", "blocked"]
    summary: str = Field(min_length=1)
    receipt_refs: list[str] = Field(default_factory=list)
    boundary: ScoutSosPlaybookBoundary = Field(default_factory=ScoutSosPlaybookBoundary)


class ScoutSosPlaybookResult(ScoutSosPlaybookModel):
    artifact_kind: Literal["scout_sos_playbook_run"] = "scout_sos_playbook_run"
    schema_version: str = "0.1.0"
    status: Literal["completed", "blocked"]
    dry_run: bool
    sos_event_id: str
    activation_source: ActivationSource
    trip_id: str
    steps: list[ScoutSosPlaybookStep]
    outbound_receipts: list[dict[str, Any]] = Field(default_factory=list)
    voice_receipts: list[dict[str, Any]] = Field(default_factory=list)
    debug_event_refs: list[str] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)
    debug_log_path: str | None = None
    voice_log_path: str | None = None
    boundary: ScoutSosPlaybookBoundary = Field(default_factory=ScoutSosPlaybookBoundary)

    @model_validator(mode="after")
    def enforce_no_real_effect_counts(self) -> "ScoutSosPlaybookResult":
        if self.counts.get("real_outbound_send_count", 0) != 0:
            raise ValueError("SOS playbook must not record real outbound sends")
        if self.counts.get("hardware_action_count", 0) != 0:
            raise ValueError("SOS playbook must not record hardware action")
        if self.counts.get("phase1_safety_mutation_count", 0) != 0:
            raise ValueError("SOS playbook must not record Phase 1 mutation")
        return self


def run_mock_sos_playbook(
    *,
    sos_event: ScoutSosActivationEvent | dict[str, Any],
    debug_log_path: str | Path | None = None,
    voice_log_path: str | Path | None = None,
    recipient_refs: list[str] | None = None,
    dry_run: bool = True,
    mock_deliver: bool = False,
    render_voice_mock: bool = True,
) -> ScoutSosPlaybookResult:
    event = ScoutSosActivationEvent.model_validate(sos_event)
    recipients = list(recipient_refs or ["remote_contact.primary"])
    planned_steps = _planned_steps(event, recipients=recipients)
    if event.activation_source == "operator_test":
        return _blocked_result(
            event,
            dry_run=dry_run,
            steps=[
                planned_steps[0].model_copy(
                    update={
                        "status": "blocked",
                        "summary": "operator_test cannot enter SOS delegated emergency mode",
                    }
                )
            ],
            debug_log_path=debug_log_path,
            voice_log_path=voice_log_path,
        )
    if dry_run:
        return _completed_result(
            event,
            dry_run=True,
            steps=planned_steps,
            debug_log_path=debug_log_path,
            voice_log_path=voice_log_path,
        )
    if debug_log_path is None:
        return _blocked_result(
            event,
            dry_run=False,
            steps=[
                planned_steps[0].model_copy(
                    update={
                        "status": "blocked",
                        "summary": "debug_log_path is required for non-dry-run SOS playbook",
                    }
                )
            ],
            debug_log_path=debug_log_path,
            voice_log_path=voice_log_path,
        )

    log = FileRuntimeDebugEventLog(debug_log_path)
    debug_refs: list[str] = []
    for sequence, step in enumerate(planned_steps[:2], start=1):
        debug_refs.append(
            _append_step_event(log, event=event, step=step, sequence=sequence).event_id
        )

    voice_transport = MockVoiceTransport(
        output_jsonl=voice_log_path,
        debug_log=log,
        session_id=f"sos_playbook.{_safe_token(event.sos_event_id)}",
        mission_id=event.trip_id,
        timestamp_factory=lambda: event.activated_at,
    )
    voice_record = voice_transport.queue_voice_cue(
        _voice_cue_for_event(event),
        engine="mock",
    )
    if render_voice_mock:
        voice_record = voice_transport.mark_rendered(voice_record.cue_id, engine="mock")
    voice_step = planned_steps[2].model_copy(
        update={"status": "completed", "receipt_refs": [voice_record.cue_id]}
    )
    debug_refs.append(
        _append_step_event(log, event=event, step=voice_step, sequence=3).event_id
    )

    outbound_transport = MockOutboundTransport(
        session_id=f"sos_playbook.{_safe_token(event.sos_event_id)}",
        mission_id=event.trip_id,
        debug_log=log,
        timestamp_factory=lambda: event.activated_at,
    )
    outbound_receipts: list[MockOutboundMessage] = []
    for recipient in recipients:
        message = outbound_transport.queue_message(
            category="incident_alert",
            recipient_ref=recipient,
            subject_ref=event.sos_event_id,
            body_preview=_sos_body(event),
            payload={
                "sos_event_id": event.sos_event_id,
                "trip_id": event.trip_id,
                "activation_source": event.activation_source,
                "position": event.position,
                "mock_outbound_only": True,
            },
            correlation_refs=[event.sos_event_id],
        )
        if mock_deliver:
            message = outbound_transport.mark_mock_delivered(message.message_id)
        outbound_receipts.append(message)
    outbound_step = planned_steps[3].model_copy(
        update={
            "status": "completed",
            "receipt_refs": [message.message_id for message in outbound_receipts],
        }
    )
    debug_refs.append(
        _append_step_event(log, event=event, step=outbound_step, sequence=4).event_id
    )

    final_step = planned_steps[4].model_copy(
        update={
            "status": "completed",
            "receipt_refs": [
                voice_record.cue_id,
                *[message.message_id for message in outbound_receipts],
            ],
        }
    )
    debug_refs.append(
        _append_step_event(log, event=event, step=final_step, sequence=5).event_id
    )
    return _completed_result(
        event,
        dry_run=False,
        steps=[
            planned_steps[0].model_copy(update={"status": "completed"}),
            planned_steps[1].model_copy(update={"status": "completed"}),
            voice_step,
            outbound_step,
            final_step,
        ],
        outbound_receipts=[message.model_dump(mode="json") for message in outbound_receipts],
        voice_receipts=[voice_record.model_dump(mode="json")],
        debug_event_refs=debug_refs,
        debug_log_path=debug_log_path,
        voice_log_path=voice_log_path,
    )


def _planned_steps(
    event: ScoutSosActivationEvent,
    *,
    recipients: list[str],
) -> list[ScoutSosPlaybookStep]:
    return [
        ScoutSosPlaybookStep(
            step_id="validate_sos_activation",
            status="planned",
            summary=f"Validate explicit SOS activation source: {event.activation_source}.",
        ),
        ScoutSosPlaybookStep(
            step_id="compose_emergency_packet",
            status="planned",
            summary="Compose local emergency packet from provided SOS event and local trip refs.",
        ),
        ScoutSosPlaybookStep(
            step_id="queue_local_voice_cue",
            status="planned",
            summary="Queue mock local urgent voice cue; no speaker playback or hardware alarm.",
        ),
        ScoutSosPlaybookStep(
            step_id="queue_mock_outbound_messages",
            status="planned",
            summary=f"Queue mock outbound incident alerts for {len(recipients)} recipient(s).",
        ),
        ScoutSosPlaybookStep(
            step_id="record_receipts",
            status="planned",
            summary="Record mock receipts and boundary metadata in the flight recorder.",
        ),
    ]


def _completed_result(
    event: ScoutSosActivationEvent,
    *,
    dry_run: bool,
    steps: list[ScoutSosPlaybookStep],
    outbound_receipts: list[dict[str, Any]] | None = None,
    voice_receipts: list[dict[str, Any]] | None = None,
    debug_event_refs: list[str] | None = None,
    debug_log_path: str | Path | None,
    voice_log_path: str | Path | None,
) -> ScoutSosPlaybookResult:
    outbound = list(outbound_receipts or [])
    voice = list(voice_receipts or [])
    return ScoutSosPlaybookResult(
        status="completed",
        dry_run=dry_run,
        sos_event_id=event.sos_event_id,
        activation_source=event.activation_source,
        trip_id=event.trip_id,
        steps=steps,
        outbound_receipts=outbound,
        voice_receipts=voice,
        debug_event_refs=list(debug_event_refs or []),
        counts={
            "playbook_step_count": len(steps),
            "mock_outbound_message_count": len(outbound),
            "voice_cue_count": len(voice),
            "real_outbound_send_count": 0,
            "hardware_action_count": 0,
            "phase1_safety_mutation_count": 0,
        },
        debug_log_path=str(debug_log_path) if debug_log_path else None,
        voice_log_path=str(voice_log_path) if voice_log_path else None,
    )


def _blocked_result(
    event: ScoutSosActivationEvent,
    *,
    dry_run: bool,
    steps: list[ScoutSosPlaybookStep],
    debug_log_path: str | Path | None,
    voice_log_path: str | Path | None,
) -> ScoutSosPlaybookResult:
    return ScoutSosPlaybookResult(
        status="blocked",
        dry_run=dry_run,
        sos_event_id=event.sos_event_id,
        activation_source=event.activation_source,
        trip_id=event.trip_id,
        steps=steps,
        counts={
            "playbook_step_count": len(steps),
            "mock_outbound_message_count": 0,
            "voice_cue_count": 0,
            "real_outbound_send_count": 0,
            "hardware_action_count": 0,
            "phase1_safety_mutation_count": 0,
        },
        debug_log_path=str(debug_log_path) if debug_log_path else None,
        voice_log_path=str(voice_log_path) if voice_log_path else None,
    )


def _append_step_event(
    log: FileRuntimeDebugEventLog | MemoryRuntimeDebugEventLog,
    *,
    event: ScoutSosActivationEvent,
    step: ScoutSosPlaybookStep,
    sequence: int,
) -> RuntimeDebugEvent:
    debug_event = RuntimeDebugEvent(
        event_id=f"debug_event.sos_playbook.{_safe_token(event.sos_event_id)}.{sequence:06d}",
        session_id=f"sos_playbook.{_safe_token(event.sos_event_id)}",
        mission_id=event.trip_id,
        timestamp=event.activated_at,
        sequence=sequence,
        kind="sos_playbook_step_recorded",
        source="scout_sos_playbook",
        phase="phase35",
        severity="warning" if step.status == "blocked" else "info",
        subject_ref=event.sos_event_id,
        correlation_refs=[event.sos_event_id, step.step_id],
        summary=step.summary,
        payload={
            "sos_event_id": event.sos_event_id,
            "activation_source": event.activation_source,
            "step_id": step.step_id,
            "status": step.status,
            "receipt_refs": step.receipt_refs,
            "boundary": step.boundary.model_dump(mode="json"),
        },
    )
    log.append(debug_event)
    return debug_event


def _voice_cue_for_event(event: ScoutSosActivationEvent) -> VoiceCue:
    return VoiceCue(
        cue_id=f"voice_cue.sos.{_safe_token(event.sos_event_id)}",
        priority="urgent",
        category="team",
        text_zh=event.message_zh or "SOS 已啟動。請保持冷靜，停留在安全位置並等待領隊確認。",
        source_event_refs=[event.sos_event_id, *event.source_refs],
        source_kind="deterministic_fact",
        confidence=1.0,
        repeat_policy=VoiceCueRepeatPolicy(
            dedupe_key=f"sos:{event.sos_event_id}",
            min_interval_seconds=30,
            max_repeats=3,
        ),
        require_ack=True,
    )


def _sos_body(event: ScoutSosActivationEvent) -> str:
    position = event.position or {}
    lat = position.get("lat")
    lon = position.get("lon")
    position_text = f" position=({lat},{lon})" if lat is not None and lon is not None else ""
    message = event.message_zh or "SOS activated by Scout."
    return (
        f"[MOCK SOS] trip={event.trip_id} event={event.sos_event_id} "
        f"source={event.activation_source}{position_text} message={message}"
    )


def _safe_token(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.:-]+", "_", value)
