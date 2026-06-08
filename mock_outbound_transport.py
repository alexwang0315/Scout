from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

from runtime_debug_models import RuntimeDebugEvent


MockOutboundMessageState = Literal[
    "queued",
    "sent",
    "failed",
    "mock-delivered",
    "cancelled",
]
MockOutboundMessageCategory = Literal[
    "remote_status",
    "checkin",
    "incident_alert",
    "provider_degraded_notice",
    "skill_output_notice",
]


class _RuntimeDebugLog(Protocol):
    def append(self, event: RuntimeDebugEvent) -> RuntimeDebugEvent:
        ...


class MockOutboundBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    real_sos_sent: bool = False
    real_sms_sent: bool = False
    real_satellite_sent: bool = False


class MockOutboundMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    created_at: str = Field(min_length=1)
    updated_at: str = Field(min_length=1)
    category: MockOutboundMessageCategory
    transport: Literal["mock"] = "mock"
    state: MockOutboundMessageState
    recipient_ref: str = Field(min_length=1)
    subject_ref: str | None = None
    body_preview: str = Field(min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)
    boundary: MockOutboundBoundary = Field(default_factory=MockOutboundBoundary)

    @field_validator("created_at", "updated_at")
    @classmethod
    def validate_timestamp(cls, value: str) -> str:
        _parse_timestamp(value)
        return value


class MockOutboundTransport:
    def __init__(
        self,
        *,
        session_id: str,
        debug_log: _RuntimeDebugLog,
        mission_id: str | None = None,
        timestamp_factory: Callable[[], str] | None = None,
    ):
        self.session_id = session_id
        self.mission_id = mission_id
        self.debug_log = debug_log
        self.timestamp_factory = timestamp_factory or _utc_now
        self._messages: dict[str, MockOutboundMessage] = {}
        self._message_sequence = 0
        self._event_sequence = 0

    def queue_message(
        self,
        *,
        category: MockOutboundMessageCategory,
        recipient_ref: str,
        body_preview: str,
        subject_ref: str | None = None,
        payload: dict[str, Any] | None = None,
        correlation_refs: list[str] | None = None,
    ) -> MockOutboundMessage:
        timestamp = self.timestamp_factory()
        self._message_sequence += 1
        message = MockOutboundMessage(
            message_id=f"mock_message.{category}.{self._message_sequence:06d}",
            session_id=self.session_id,
            created_at=timestamp,
            updated_at=timestamp,
            category=category,
            state="queued",
            recipient_ref=recipient_ref,
            subject_ref=subject_ref,
            body_preview=body_preview,
            payload=dict(payload or {}),
        )
        self._messages[message.message_id] = message
        self._append_debug_event(
            kind="outbound_message_queued",
            message=message,
            timestamp=timestamp,
            correlation_refs=correlation_refs or [],
        )
        return message

    def mark_sent(self, message_id: str) -> MockOutboundMessage:
        return self._transition(message_id, "sent")

    def mark_failed(self, message_id: str, *, reason: str) -> MockOutboundMessage:
        return self._transition(message_id, "failed", reason=reason)

    def mark_mock_delivered(self, message_id: str) -> MockOutboundMessage:
        return self._transition(message_id, "mock-delivered")

    def cancel_message(self, message_id: str, *, reason: str) -> MockOutboundMessage:
        return self._transition(message_id, "cancelled", reason=reason)

    def list_messages(self) -> list[MockOutboundMessage]:
        return list(self._messages.values())

    def get_message(self, message_id: str) -> MockOutboundMessage:
        return self._messages[message_id]

    def _transition(
        self,
        message_id: str,
        state: MockOutboundMessageState,
        *,
        reason: str | None = None,
    ) -> MockOutboundMessage:
        current = self._messages[message_id]
        timestamp = self.timestamp_factory()
        updated = MockOutboundMessage.model_validate(
            {**current.model_dump(mode="json"), "state": state, "updated_at": timestamp}
        )
        self._messages[message_id] = updated
        self._append_debug_event(
            kind="outbound_message_state_changed",
            message=updated,
            timestamp=timestamp,
            reason=reason,
        )
        return updated

    def _append_debug_event(
        self,
        *,
        kind: Literal["outbound_message_queued", "outbound_message_state_changed"],
        message: MockOutboundMessage,
        timestamp: str,
        correlation_refs: list[str] | None = None,
        reason: str | None = None,
    ) -> None:
        self._event_sequence += 1
        payload: dict[str, Any] = {
            "message_id": message.message_id,
            "category": message.category,
            "transport": message.transport,
            "state": message.state,
            "recipient_ref": message.recipient_ref,
            "subject_ref": message.subject_ref,
            "body_preview": message.body_preview,
            "boundary": message.boundary.model_dump(mode="json"),
        }
        if reason is not None:
            payload["reason"] = reason
        event = RuntimeDebugEvent(
            event_id=f"debug_event.mock_outbound.{self._event_sequence:06d}",
            session_id=self.session_id,
            mission_id=self.mission_id,
            timestamp=timestamp,
            sequence=self._event_sequence,
            kind=kind,
            source="mock_outbound_transport",
            phase="phase35",
            severity="warning" if message.state == "failed" else "info",
            subject_ref=message.message_id,
            correlation_refs=list(correlation_refs or []),
            summary=f"Mock outbound message {message.state}.",
            payload=payload,
        )
        if hasattr(self.debug_log, "try_append"):
            self.debug_log.try_append(event)
            return
        self.debug_log.append(event)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
