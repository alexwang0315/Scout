from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


VoiceCuePriority = Literal["info", "caution", "warning", "urgent"]
VoiceCueCategory = Literal["route", "body", "weather", "device", "team", "environment"]
VoiceCueSourceKind = Literal[
    "deterministic_fact",
    "read_only_model_interpretation",
    "operator_note",
]


class VoiceCueContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VoiceCueBoundary(VoiceCueContractModel):
    local_awareness_channel: Literal[True] = True
    safety_decision_change_allowed: Literal[False] = False
    phase1_safety_runtime_mutation_allowed: Literal[False] = False
    remote_outbound_allowed: Literal[False] = False
    hardware_control_allowed: Literal[False] = False
    sos_trigger_allowed: Literal[False] = False
    sms_send_allowed: Literal[False] = False
    satellite_send_allowed: Literal[False] = False
    model_interpretation_must_be_read_only: Literal[True] = True
    endpoint_calls: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def enforce_no_endpoint_calls(self) -> "VoiceCueBoundary":
        if self.endpoint_calls:
            raise ValueError("voice cue layer must not call runtime endpoints")
        return self


class VoiceCueRepeatPolicy(VoiceCueContractModel):
    dedupe_key: str | None = Field(default=None, min_length=1)
    min_interval_seconds: int = Field(default=300, ge=0)
    max_repeats: int | None = Field(default=1, ge=0)


class VoiceCue(VoiceCueContractModel):
    cue_id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_.:-]+$")
    priority: VoiceCuePriority
    category: VoiceCueCategory
    text_zh: str = Field(min_length=1)
    source_event_refs: list[str] = Field(default_factory=list)
    source_kind: VoiceCueSourceKind = "deterministic_fact"
    confidence: float = Field(ge=0, le=1)
    expires_at: str | None = None
    repeat_policy: VoiceCueRepeatPolicy = Field(default_factory=VoiceCueRepeatPolicy)
    require_ack: bool = False
    spoken_allowed: bool = True
    boundary: VoiceCueBoundary = Field(default_factory=VoiceCueBoundary)

    @field_validator("expires_at")
    @classmethod
    def validate_expires_at(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("expires_at must be ISO-8601 compatible") from exc
        return value

    @model_validator(mode="after")
    def enforce_spoken_contract(self) -> "VoiceCue":
        if self.spoken_allowed and not self.text_zh.strip():
            raise ValueError("spoken voice cues require non-empty text_zh")
        if self.source_kind == "read_only_model_interpretation":
            if not self.boundary.model_interpretation_must_be_read_only:
                raise ValueError("model interpretation voice cues must stay read-only")
        return self

    @property
    def dedupe_key(self) -> str:
        return self.repeat_policy.dedupe_key or f"{self.category}:{self.text_zh}"
