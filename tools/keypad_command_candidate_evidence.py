from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any


SOURCE = "pi_scout_agent_keypad_command"
HARDWARE_KIND = "matrix_keypad_4x4_agent_command_bridge"
CONFIRM_COMMAND = "confirm_pending"
CONFIRM_KEY_PHYSICAL_LABEL = "S15"
DEFAULT_CONFIRMATION_TIMEOUT_SECONDS = 10.0

ALLOWED_LOCAL_COMMANDS = frozenset(
    {
        "gps_status",
        "wifi_status",
        "runtime_health",
        "clear_oled",
        "led_test",
    }
)

KEY_TO_LOCAL_COMMAND = {
    "1": "gps_status",
    "2": "wifi_status",
    "3": "runtime_health",
    "4": "clear_oled",
    "5": "led_test",
    "*": "clear_oled",
    "#": CONFIRM_COMMAND,
    "A": "safety_l4_direct_trigger",
    "B": "remote_ack_i_am_ok",
    "C": "safety_mark_event_mutation",
    "D": "runtime_health",
}

COMMAND_LABELS = {
    "gps_status": "GPS STATUS",
    "wifi_status": "WIFI STATUS",
    "runtime_health": "RUNTIME",
    "clear_oled": "CLEAR OLED",
    "led_test": "LED TEST",
    CONFIRM_COMMAND: "CONFIRM",
    "safety_l4_direct_trigger": "L4 DIRECT",
    "remote_ack_i_am_ok": "ACK OUTBOUND",
    "safety_mark_event_mutation": "SAFETY EVENT",
}


@dataclass(frozen=True)
class CandidatePolicy:
    confirmation_timeout_seconds: float = DEFAULT_CONFIRMATION_TIMEOUT_SECONDS
    confirmation_key_physical_label: str = CONFIRM_KEY_PHYSICAL_LABEL
    expire_pending_at_end: bool = True


def mapped_command_for_agent_event(agent_event: dict[str, Any]) -> str:
    key = str(agent_event.get("key", "")).upper()
    return KEY_TO_LOCAL_COMMAND.get(key, "runtime_health")


def command_label(mapped_command: str) -> str:
    return COMMAND_LABELS.get(mapped_command, mapped_command.replace("_", " ").upper())


def command_block_reason(mapped_command: str) -> str | None:
    if mapped_command in ALLOWED_LOCAL_COMMANDS or mapped_command == CONFIRM_COMMAND:
        return None
    lowered = mapped_command.lower()
    if "l4" in lowered:
        return "l4_direct_trigger_blocked"
    if "outbound" in lowered or "ack" in lowered:
        return "remote_outbound_blocked"
    if "safety" in lowered or "sos" in lowered:
        return "safety_mutation_blocked"
    return "command_not_allowed"


def build_candidate_evidence_flow(
    agent_events: list[dict[str, Any]],
    *,
    policy: CandidatePolicy | None = None,
) -> list[dict[str, Any]]:
    active_policy = policy or CandidatePolicy()
    evidence_events: list[dict[str, Any]] = []
    pending: dict[str, Any] | None = None

    for agent_event in agent_events:
        event_time = _event_time(agent_event)
        if pending is not None and _is_expired(pending, event_time):
            evidence_events.append(
                _transition_event(
                    source_event=pending,
                    status="expired",
                    event_name="command_candidate_expired",
                    occurred_at=_iso(event_time),
                    reason="confirmation_timeout",
                )
            )
            pending = None

        mapped_command = mapped_command_for_agent_event(agent_event)
        if mapped_command == CONFIRM_COMMAND:
            if pending is None:
                evidence_events.append(
                    _candidate_event(
                        agent_event=agent_event,
                        mapped_command=mapped_command,
                        status="blocked",
                        event_name="command_candidate_blocked",
                        policy=active_policy,
                        block_reason="no_pending_candidate",
                    )
                )
                continue
            evidence_events.append(
                _transition_event(
                    source_event=pending,
                    status="confirmed",
                    event_name="command_candidate_confirmed",
                    occurred_at=_iso(event_time),
                    reason=None,
                    confirmation_key=str(agent_event.get("physical_label", "")),
                    confirmation_sequence=agent_event.get("sequence"),
                )
            )
            pending = None
            continue

        block_reason = command_block_reason(mapped_command)
        if block_reason is not None:
            evidence_events.append(
                _candidate_event(
                    agent_event=agent_event,
                    mapped_command=mapped_command,
                    status="blocked",
                    event_name="command_candidate_blocked",
                    policy=active_policy,
                    block_reason=block_reason,
                )
            )
            continue

        if pending is not None:
            evidence_events.append(
                _transition_event(
                    source_event=pending,
                    status="expired",
                    event_name="command_candidate_expired",
                    occurred_at=_iso(event_time),
                    reason="superseded_by_new_candidate",
                )
            )
        pending = _candidate_event(
            agent_event=agent_event,
            mapped_command=mapped_command,
            status="created",
            event_name="command_candidate_created",
            policy=active_policy,
            block_reason=None,
        )
        evidence_events.append(pending)

    if pending is not None and active_policy.expire_pending_at_end:
        expires_at = _parse_iso(str(pending["expires_at"]))
        evidence_events.append(
            _transition_event(
                source_event=pending,
                status="expired",
                event_name="command_candidate_expired",
                occurred_at=_iso(expires_at),
                reason="confirmation_timeout",
            )
        )

    return evidence_events


def candidate_oled_message(evidence_event: dict[str, Any]) -> str:
    label = command_label(str(evidence_event["mapped_command"]))
    status = str(evidence_event["candidate_status"]).upper()
    reason = str(evidence_event.get("block_reason") or evidence_event.get("transition_reason") or "")
    if status == "CREATED":
        lines = ["SCOUT CMD", label, "CREATED", "PRESS #", "LOCAL ONLY"]
    elif status == "CONFIRMED":
        lines = ["SCOUT CMD", label, "CONFIRMED", "LOCAL ONLY", "NO SAFETY MUT"]
    elif status == "EXPIRED":
        lines = ["SCOUT CMD", label, "EXPIRED", "PRESS AGAIN", "DIAG ONLY"]
    else:
        reason_label = reason.replace("_", " ").upper()[:16] if reason else "BLOCKED"
        lines = ["SCOUT CMD", label, "BLOCKED", reason_label, "NO SAFETY MUT"]
    return "\n".join(line[:16] for line in lines)


def led_bits_for_candidate_status(evidence_event: dict[str, Any]) -> int:
    status = evidence_event["candidate_status"]
    if status == "confirmed":
        return 0x3FF
    if status == "expired":
        return 0x155
    if status == "blocked":
        return 0x2AA
    key_index = int(evidence_event["row_index"]) * 4 + int(evidence_event["col_index"])
    return 1 << (key_index % 10)


def _candidate_event(
    *,
    agent_event: dict[str, Any],
    mapped_command: str,
    status: str,
    event_name: str,
    policy: CandidatePolicy,
    block_reason: str | None,
) -> dict[str, Any]:
    captured_at = str(agent_event.get("captured_at") or datetime.now(timezone.utc).isoformat())
    event_time = _parse_iso(captured_at)
    expires_at = event_time + timedelta(seconds=policy.confirmation_timeout_seconds)
    candidate_id = _candidate_id(agent_event=agent_event, mapped_command=mapped_command)
    local_allowed = mapped_command in ALLOWED_LOCAL_COMMANDS
    evidence = {
        "captured_at": captured_at,
        "source": SOURCE,
        "hardware_kind": HARDWARE_KIND,
        "event": event_name,
        "candidate_id": candidate_id,
        "candidate_status": status,
        "key_id": agent_event.get("physical_label"),
        "key": agent_event.get("key"),
        "physical_label": agent_event.get("physical_label"),
        "physical_label_layout": agent_event.get("physical_label_layout"),
        "row_index": agent_event.get("row_index"),
        "col_index": agent_event.get("col_index"),
        "row_gpio": agent_event.get("row_gpio"),
        "col_gpio": agent_event.get("col_gpio"),
        "sequence": agent_event.get("sequence"),
        "suggested_control_role": agent_event.get("suggested_control_role"),
        "agent_command_id": agent_event.get("agent_command_id"),
        "skill_candidate_id": f"scout.skill.keypad.{mapped_command}",
        "mapped_command": mapped_command,
        "mapped_command_label": command_label(mapped_command),
        "local_diagnostic_command_allowed": local_allowed,
        "confirmation_required": local_allowed,
        "confirmation_key_physical_label": policy.confirmation_key_physical_label,
        "expires_at": _iso(expires_at) if local_allowed else None,
        "block_reason": block_reason,
        "agent_command_execution_allowed": False,
        "local_command_dispatch_allowed": status == "confirmed" and local_allowed,
        "phase1_safety_decision_change_allowed": False,
        "safety_level_mutation_allowed": False,
        "live_safety_api_called": False,
        "live_safety_api_mutation_allowed": False,
        "remote_outbound_allowed": False,
        "remote_outbound_send_allowed": False,
        "hardware_control_scope": "agent_command_candidate_evidence_only",
        "visual_updates": [],
    }
    return evidence


def _transition_event(
    *,
    source_event: dict[str, Any],
    status: str,
    event_name: str,
    occurred_at: str,
    reason: str | None,
    confirmation_key: str | None = None,
    confirmation_sequence: Any | None = None,
) -> dict[str, Any]:
    event = dict(source_event)
    event["captured_at"] = occurred_at
    event["event"] = event_name
    event["candidate_status"] = status
    event["transition_reason"] = reason
    event["confirmation_key"] = confirmation_key
    event["confirmation_sequence"] = confirmation_sequence
    event["local_command_dispatch_allowed"] = status == "confirmed" and bool(
        event.get("local_diagnostic_command_allowed")
    )
    event["visual_updates"] = []
    return event


def _candidate_id(*, agent_event: dict[str, Any], mapped_command: str) -> str:
    physical_label = str(agent_event.get("physical_label") or "unknown").lower()
    sequence = str(agent_event.get("sequence", "0"))
    return f"keypad-{physical_label}-{sequence}-{mapped_command}"


def _event_time(agent_event: dict[str, Any]) -> datetime:
    return _parse_iso(str(agent_event.get("captured_at") or datetime.now(timezone.utc).isoformat()))


def _parse_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _is_expired(pending: dict[str, Any], event_time: datetime) -> bool:
    expires_at = pending.get("expires_at")
    if not expires_at:
        return False
    return event_time >= _parse_iso(str(expires_at))


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()
