"""Deterministic power-mode classification and model fallback supervision.

This module is deliberately independent from LLM/Jev code. It consumes only
typed, read-only telemetry and produces an auditable transition decision.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
from typing import Any, Callable, Literal

PowerMode = Literal["direct", "ups", "unknown"]
SafetyState = Literal["NORMAL_HAILO", "SAFETY_ALERT", "CPU_FALLBACK", "SAFE_STOP"]
HumanChoice = Literal["continue_hailo", "cpu_fallback", "stop"]


@dataclass(frozen=True)
class PowerModeDecision:
    power_mode: PowerMode
    reason: str
    evidence: dict[str, Any]
    ups_battery_status: Literal["applicable", "not_applicable", "unknown"]

    def as_dict(self) -> dict[str, Any]:
        return {
            "power_mode": self.power_mode,
            "reason": self.reason,
            "evidence": self.evidence,
            "ups_battery_status": self.ups_battery_status,
        }


@dataclass(frozen=True)
class SafetyTransition:
    state_before: SafetyState
    state_after: SafetyState
    event: str
    choice: HumanChoice | None = None
    timed_out: bool = False
    fallback_requested: bool = False
    fallback_status: str | None = None
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "state_before": self.state_before,
            "state_after": self.state_after,
            "event": self.event,
            "choice": self.choice,
            "timed_out": self.timed_out,
            "fallback_requested": self.fallback_requested,
            "fallback_status": self.fallback_status,
            "reason": self.reason,
        }


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def classify_power_mode(
    health: dict[str, Any],
    *,
    now: datetime | None = None,
    stale_after_seconds: float = 15.0,
) -> PowerModeDecision:
    """Classify direct/UPS/unknown without treating UPS presence as UPS power."""

    path = health.get("power_path")
    if not isinstance(path, dict) or not path.get("available"):
        return PowerModeDecision("unknown", "power_path_telemetry_unavailable", {"power_path": path}, "unknown")
    if path.get("fresh") is not True:
        return PowerModeDecision("unknown", "power_path_telemetry_stale_or_unverified", {"power_path": path}, "unknown")
    latest = path.get("latest")
    if not isinstance(latest, dict):
        return PowerModeDecision("unknown", "power_path_latest_sample_missing", {"power_path": path}, "unknown")
    errors = latest.get("errors")
    if errors not in (None, [], {}):
        return PowerModeDecision("unknown", "power_path_sample_has_errors", {"power_path": path, "errors": errors}, "unknown")
    captured_at = latest.get("captured_at")
    try:
        captured = datetime.fromisoformat(str(captured_at))
        if captured.tzinfo is None:
            captured = captured.replace(tzinfo=timezone.utc)
        reference = now or datetime.now(timezone.utc)
        age_seconds = (reference - captured).total_seconds()
    except (TypeError, ValueError):
        age_seconds = None
    if age_seconds is None or not -5 <= age_seconds <= stale_after_seconds:
        return PowerModeDecision("unknown", "power_path_sample_timestamp_invalid_or_stale", {"power_path": path, "age_seconds": age_seconds}, "unknown")

    ext5v = _finite_number(latest.get("ext5v_v"))
    vbus_voltage = _finite_number(latest.get("ups_vbus_voltage_mv"))
    vbus_current = _finite_number(latest.get("ups_vbus_current_ma"))
    vbus_power = _finite_number(latest.get("ups_vbus_power_mw"))
    battery_current = _finite_number(latest.get("battery_current_ma"))
    flow = str(latest.get("battery_current_flow") or "").casefold()
    power_state = str(latest.get("ups_power_state") or "").casefold()
    evidence = {
        "captured_at": captured.isoformat(),
        "age_seconds": round(age_seconds, 3),
        "ext5v_v": ext5v,
        "ups_vbus_voltage_mv": vbus_voltage,
        "ups_vbus_current_ma": vbus_current,
        "ups_vbus_power_mw": vbus_power,
        "battery_current_ma": battery_current,
        "battery_current_flow": flow or None,
        "ups_power_state": power_state or None,
    }
    direct = (
        ext5v is not None and ext5v >= 4.8
        and (vbus_voltage or 0) <= 50 and (vbus_current or 0) <= 50
        and (vbus_power or 0) <= 50 and flow in {"", "idle"}
        and power_state in {"", "idle"}
    )
    if direct:
        return PowerModeDecision("direct", "external_5v_present_and_ups_not_powering_host", evidence, "not_applicable")
    ups_active = (
        flow == "discharging" or power_state == "discharging"
        or (vbus_power is not None and vbus_power > 50)
        or (vbus_current is not None and vbus_current > 50)
    )
    if ups_active:
        return PowerModeDecision("ups", "ups_is_powering_host", evidence, "applicable")
    return PowerModeDecision("unknown", "power_path_has_no_unambiguous_direct_or_ups_signature", evidence, "unknown")


class PowerSafetySupervisor:
    """Own the only allowed transition from Hailo to a CPU fallback."""

    def __init__(self, *, fallback_script: Path | None = None) -> None:
        self.fallback_script = fallback_script

    def inspect_hailo(self, health: dict[str, Any]) -> SafetyTransition:
        decision = classify_power_mode(health)
        if decision.power_mode == "direct":
            return SafetyTransition("NORMAL_HAILO", "NORMAL_HAILO", "power_mode_direct", reason=decision.reason)
        return SafetyTransition("NORMAL_HAILO", "SAFETY_ALERT", "power_mode_requires_human_confirmation", reason=decision.reason)

    def resolve_alert(self, *, choice: HumanChoice | None = None, timed_out: bool = False) -> SafetyTransition:
        if choice == "continue_hailo":
            return SafetyTransition("SAFETY_ALERT", "NORMAL_HAILO", "human_confirmed_continue_hailo", choice=choice)
        if choice == "cpu_fallback":
            return SafetyTransition("SAFETY_ALERT", "CPU_FALLBACK", "human_confirmed_cpu_fallback", choice=choice, fallback_requested=True)
        if choice == "stop":
            return SafetyTransition("SAFETY_ALERT", "SAFE_STOP", "human_confirmed_stop", choice=choice)
        if timed_out:
            return SafetyTransition("SAFETY_ALERT", "CPU_FALLBACK", "safety_timeout_allowlisted_fallback", timed_out=True, fallback_requested=True)
        return SafetyTransition("SAFETY_ALERT", "SAFETY_ALERT", "awaiting_human_confirmation")

    def run_allowlisted_fallback(
        self,
        *,
        command: list[str],
        allowlisted_script: Path,
        timeout_seconds: float = 30.0,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ) -> SafetyTransition:
        """Run only the exact approved script and fail closed on any error."""
        try:
            expected = allowlisted_script.resolve()
            actual = Path(command[0]).resolve()
            if actual != expected or actual.name != "scout_ai_cpu_fallback_allowlisted.sh":
                raise ValueError("fallback_script_not_allowlisted")
            if not actual.is_file() or not actual.stat().st_mode & 0o111:
                raise ValueError("fallback_script_not_executable")
            completed = runner(command, check=False, capture_output=True, text=True, timeout=timeout_seconds)
            if completed.returncode != 0:
                return SafetyTransition("SAFETY_ALERT", "SAFE_STOP", "allowlisted_fallback_failed", fallback_requested=True, fallback_status=f"returncode_{completed.returncode}")
            return SafetyTransition("SAFETY_ALERT", "CPU_FALLBACK", "allowlisted_fallback_started", fallback_requested=True, fallback_status="started")
        except Exception as exc:  # noqa: BLE001 - safety path fails closed.
            return SafetyTransition("SAFETY_ALERT", "SAFE_STOP", "allowlisted_fallback_failed", fallback_requested=True, fallback_status=f"{type(exc).__name__}:{exc}")


def append_transition(path: Path, transition: SafetyTransition) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(transition.as_dict(), ensure_ascii=False) + "\n")
