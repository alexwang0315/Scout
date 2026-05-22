from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


RuntimeDebugEventKind = Literal[
    "observation_ingested",
    "route_progress_evaluated",
    "checkpoint_detected",
    "progress_update_recorded",
    "recording_policy_selected",
    "safety_event_emitted",
    "safety_transition_recorded",
    "incident_package_created",
    "incident_package_persisted",
    "phase3_bridge_result",
    "provider_status_recorded",
    "ln_activation_gate_evaluated",
    "skill_run_recorded",
    "outbound_message_queued",
    "outbound_message_state_changed",
    "voice_cue_queued",
    "voice_cue_state_changed",
    "debug_session_started",
    "debug_session_completed",
]


class RuntimeDebugEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    mission_id: str | None = None
    timestamp: str = Field(min_length=1)
    sequence: int = Field(ge=0)
    kind: RuntimeDebugEventKind
    source: str = Field(min_length=1)
    phase: Literal["phase1", "phase2", "phase3", "phase35"]
    severity: Literal["debug", "info", "warning", "error"] = "info"
    subject_ref: str | None = None
    correlation_refs: list[str] = Field(default_factory=list)
    summary: str = Field(min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp(cls, value: str) -> str:
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("timestamp must be ISO-8601 compatible") from exc
        return value
