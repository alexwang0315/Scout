from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

try:
    from tools.keypad_command_candidate_evidence import ALLOWED_LOCAL_COMMANDS, command_label
except ImportError:  # pragma: no cover - used when executed directly from tools/ on a Pi.
    from keypad_command_candidate_evidence import ALLOWED_LOCAL_COMMANDS, command_label


SOURCE = "pi_scout_agent_keypad_command"
HARDWARE_KIND = "matrix_keypad_4x4_agent_command_bridge"
DISPATCH_EVENT = "local_diagnostic_command_dispatch"
DISPATCH_SCOPE = "local_diagnostic_command_dispatch_evidence_only"

StatusProvider = Callable[[str, bool], dict[str, Any]]


def build_local_diagnostic_dispatch_events(
    candidate_events: list[dict[str, Any]],
    *,
    dispatch_enabled: bool,
    dry_run: bool,
    status_provider: StatusProvider | None = None,
) -> list[dict[str, Any]]:
    if not dispatch_enabled:
        return []

    provider = status_provider or default_status_provider
    dispatch_events: list[dict[str, Any]] = []
    for candidate_event in candidate_events:
        if not _is_dispatchable_candidate(candidate_event):
            continue
        mapped_command = str(candidate_event["mapped_command"])
        result = provider(mapped_command, dry_run)
        dispatch_events.append(
            {
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "source": SOURCE,
                "hardware_kind": HARDWARE_KIND,
                "event": DISPATCH_EVENT,
                "candidate_id": candidate_event["candidate_id"],
                "candidate_status": candidate_event["candidate_status"],
                "key_id": candidate_event.get("key_id"),
                "key": candidate_event.get("key"),
                "physical_label": candidate_event.get("physical_label"),
                "physical_label_layout": candidate_event.get("physical_label_layout"),
                "row_index": candidate_event.get("row_index"),
                "col_index": candidate_event.get("col_index"),
                "row_gpio": candidate_event.get("row_gpio"),
                "col_gpio": candidate_event.get("col_gpio"),
                "sequence": candidate_event.get("sequence"),
                "agent_command_id": candidate_event.get("agent_command_id"),
                "skill_candidate_id": candidate_event.get("skill_candidate_id"),
                "mapped_command": mapped_command,
                "mapped_command_label": command_label(mapped_command),
                "dispatch_status": str(result.get("status", "recorded")),
                "dispatch_mode": "dry_run" if dry_run else "local_only",
                "dispatch_result": result,
                "local_diagnostic_command_allowed": True,
                "local_diagnostic_command_dispatch_requested": True,
                "local_diagnostic_command_dispatched": not dry_run,
                "agent_command_execution_allowed": False,
                "phase1_safety_decision_change_allowed": False,
                "safety_level_mutation_allowed": False,
                "live_safety_api_called": False,
                "live_safety_api_mutation_allowed": False,
                "remote_outbound_allowed": False,
                "remote_outbound_send_allowed": False,
                "hardware_control_scope": DISPATCH_SCOPE,
                "visual_updates": [],
            }
        )
    return dispatch_events


def default_status_provider(mapped_command: str, dry_run: bool) -> dict[str, Any]:
    if dry_run:
        return {
            "status": "planned",
            "provider": "keypad_local_diagnostic_command_dispatch",
            "message": "confirmed local diagnostic command would be dispatched",
            "sampled_live_provider": False,
        }
    return {
        "status": "recorded",
        "provider": "keypad_local_diagnostic_command_dispatch",
        "message": "confirmed local diagnostic command recorded for local-only handling",
        "sampled_live_provider": False,
        "provider_hint": _provider_hint(mapped_command),
    }


def dispatch_oled_message(dispatch_event: dict[str, Any]) -> str:
    label = command_label(str(dispatch_event["mapped_command"]))
    status = str(dispatch_event["dispatch_status"]).upper()
    lines = ["SCOUT LOCAL", label, status, "LOCAL ONLY", "NO SAFETY MUT"]
    return "\n".join(line[:16] for line in lines)


def led_bits_for_dispatch_status(dispatch_event: dict[str, Any]) -> int:
    status = str(dispatch_event.get("dispatch_status", "recorded"))
    if status in {"recorded", "completed"}:
        return 0x3FF
    if status == "planned":
        return 0x1FF
    return 0x2AA


def _is_dispatchable_candidate(candidate_event: dict[str, Any]) -> bool:
    return (
        candidate_event.get("event") == "command_candidate_confirmed"
        and candidate_event.get("candidate_status") == "confirmed"
        and bool(candidate_event.get("local_command_dispatch_allowed"))
        and str(candidate_event.get("mapped_command")) in ALLOWED_LOCAL_COMMANDS
    )


def _provider_hint(mapped_command: str) -> str:
    if mapped_command == "gps_status":
        return "tools/pi_gnss_nmea_smoke.py"
    if mapped_command == "wifi_status":
        return "tools/pi_wifi_oled_status.py"
    if mapped_command == "runtime_health":
        return "local Scout runtime health probe"
    if mapped_command == "clear_oled":
        return "tools/pi_oled_i2c_smoke.py"
    if mapped_command == "led_test":
        return "tools/pi_grove_led_bar_smoke.py"
    return "local diagnostic provider"
