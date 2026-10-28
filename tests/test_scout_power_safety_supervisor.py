from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import subprocess

from scout.hardware.power_safety_supervisor import PowerSafetySupervisor, classify_power_mode


def _health(power_path: dict, **ups) -> dict:
    return {"power_path": power_path, "ups": {"ups_hat_e": ups}}


def _path(now: str, **overrides) -> dict:
    latest = {
        "captured_at": now, "ext5v_v": 5.09,
        "ups_vbus_voltage_mv": 0, "ups_vbus_current_ma": 0,
        "ups_vbus_power_mw": 0, "battery_current_ma": 0,
        "battery_current_flow": "idle", "ups_power_state": "idle", "errors": [],
    }
    latest.update(overrides)
    return {"available": True, "fresh": True, "latest": latest}


def test_direct_power_marks_ups_metrics_not_applicable_even_with_fake_low_battery() -> None:
    decision = classify_power_mode(_health(_path("2026-09-22T00:00:00+00:00", battery_percent=1, cell_voltage_mv=[2800] * 4)), now=datetime(2026, 9, 22, tzinfo=timezone.utc))
    assert decision.power_mode == "direct"
    assert decision.ups_battery_status == "not_applicable"


def test_ups_low_power_enters_safety_alert_without_silent_cpu_switch() -> None:
    health = _health(_path("2026-09-22T00:00:00+00:00", battery_current_flow="discharging", ups_power_state="discharging", ups_vbus_power_mw=4200), battery={"percent": 8}, low_cell_voltage_present=True)
    supervisor = PowerSafetySupervisor()
    assert classify_power_mode(health, now=datetime(2026, 9, 22, tzinfo=timezone.utc)).power_mode == "ups"
    assert supervisor.inspect_hailo(health).state_after == "SAFETY_ALERT"
    assert supervisor.resolve_alert().state_after == "SAFETY_ALERT"


def test_human_cpu_choice_is_a_separate_fallback_transition() -> None:
    transition = PowerSafetySupervisor().resolve_alert(choice="cpu_fallback")
    assert transition.state_after == "CPU_FALLBACK"
    assert transition.fallback_requested is True


def test_timeout_requests_allowlisted_fallback() -> None:
    transition = PowerSafetySupervisor().resolve_alert(timed_out=True)
    assert transition.state_after == "CPU_FALLBACK"
    assert transition.timed_out is True
    assert transition.fallback_requested is True


def test_fallback_failure_enters_safe_stop(tmp_path: Path) -> None:
    script = tmp_path / "scout_ai_cpu_fallback_allowlisted.sh"
    script.write_text("#!/bin/sh\nexit 7\n", encoding="utf-8")
    script.chmod(0o755)
    transition = PowerSafetySupervisor().run_allowlisted_fallback(
        command=[str(script), "--run-id", "cpu-test"], allowlisted_script=script,
        runner=lambda *args, **kwargs: subprocess.CompletedProcess(args=args[0], returncode=7, stdout="", stderr="failed"),
    )
    assert transition.state_after == "SAFE_STOP"
    assert transition.fallback_status == "returncode_7"


def test_unknown_power_mode_requires_confirmation() -> None:
    assert classify_power_mode({"ups": {"ups_hat_e": {"available": True}}}).power_mode == "unknown"
    assert PowerSafetySupervisor().inspect_hailo({}).state_after == "SAFETY_ALERT"
