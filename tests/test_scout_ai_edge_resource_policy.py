from __future__ import annotations

from datetime import UTC, datetime, timedelta

from scout.nextgen.edge_resource_policy import (
    EdgeBackgroundResourcePolicy,
    EdgeResourceSnapshot,
    LinuxEdgeResourceMonitor,
)


def test_linux_resource_monitor_parses_pi_style_files(tmp_path) -> None:
    meminfo = tmp_path / "meminfo"
    meminfo.write_text(
        "MemTotal:        8192000 kB\n"
        "MemAvailable:    4194304 kB\n"
        "SwapTotal:       524288 kB\n"
        "SwapFree:        393216 kB\n",
        encoding="utf-8",
    )
    thermal = tmp_path / "temp"
    thermal.write_text("62500\n", encoding="utf-8")
    monitor = LinuxEdgeResourceMonitor(
        meminfo_path=meminfo,
        thermal_path=thermal,
        throttled_reader=lambda: False,
        battery_reader=lambda: 64.5,
    )

    snapshot = monitor.snapshot()

    assert snapshot.available_memory_mb == 4096
    assert snapshot.swap_used_mb == 128
    assert snapshot.cpu_temperature_c == 62.5
    assert snapshot.throttled is False
    assert snapshot.battery_percent == 64.5
    assert snapshot.runtime_safety_truth is False


def test_resource_policy_fails_closed_for_stale_or_unknown_telemetry() -> None:
    now = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)
    snapshot = EdgeResourceSnapshot(
        observed_at=now - timedelta(seconds=31),
        available_memory_mb=4096,
        swap_used_mb=0,
        cpu_temperature_c=None,
        throttled=None,
        battery_percent=15,
        source="test-monitor",
    )

    reasons = EdgeBackgroundResourcePolicy().rejection_reasons(snapshot, now=now)

    assert reasons == (
        "edge resource snapshot is stale",
        "CPU temperature is unavailable or above the maximum",
        "edge throttle state is unavailable",
        "battery is below the background minimum",
    )
