from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from tools.macos_resource_monitor import (
    CommandResult,
    MacResourceCollector,
    create_resource_monitor_app,
    parse_memory_pressure,
    parse_pmset_thermal,
    parse_top_cpu,
    parse_vm_stat,
)


VM_STAT = """Mach Virtual Memory Statistics: (page size of 4096 bytes)
Pages free:                                100.
Pages active:                              300.
Pages inactive:                            200.
Pages speculative:                          10.
Pages wired down:                          250.
Pages purgeable:                            20.
Pages occupied by compressor:               40.
"""

TOP = """Processes: 10 total, 2 running, 8 sleeping
Load Avg: 1.00, 0.80, 0.60
CPU usage: 22.50% user, 17.50% sys, 60.00% idle
"""


def fixture_runner(argv, _timeout_seconds: float) -> CommandResult:
    command = Path(argv[0]).name
    if command == "sysctl":
        return CommandResult(0, "4\n8589934592\nMacBookPro14,1\n13.7.8\n")
    if command == "top":
        return CommandResult(0, TOP)
    if command == "vm_stat":
        return CommandResult(0, VM_STAT)
    if command == "memory_pressure":
        return CommandResult(0, "System-wide memory free percentage: 64%\n")
    if command == "pmset" and "batt" in argv:
        return CommandResult(
            0,
            "Now drawing from 'AC Power'\n"
            "-InternalBattery-0\t77%; charging; 0:24 remaining present: true\n",
        )
    if command == "pmset" and "therm" in argv:
        return CommandResult(
            0,
            "Note: No thermal warning level has been recorded\n"
            "CPU_Scheduler_Limit = 100\n"
            "CPU_Available_CPUs = 4\n"
            "CPU_Speed_Limit = 100\n",
        )
    if command == "ps":
        return CommandResult(
            0,
            "123 1 12.50 4.25 123456 01:02:03 "
            "/Users/test/scout-fusion/venv/bin/python -m uvicorn "
            "phase4_admin_runtime:app --token SECRET_VALUE\n"
            "124 1 3.00 1.00 65536 00:01:02 /usr/bin/ollama serve\n"
            "125 1 80.00 8.00 999999 00:00:10 /usr/bin/unrelated-worker\n",
        )
    return CommandResult(127, stderr=f"missing fixture for {command}")


def test_parsers_decode_macos_command_summaries() -> None:
    assert parse_top_cpu(TOP) == {
        "user": 22.5,
        "system": 17.5,
        "idle": 60.0,
        "active": 40.0,
    }
    page_size, pages = parse_vm_stat(VM_STAT)
    assert page_size == 4096
    assert pages["pages free"] == 100
    assert pages["pages occupied by compressor"] == 40
    assert parse_memory_pressure("System-wide memory free percentage: 64%") == 64.0
    assert parse_pmset_thermal("CPU_Speed_Limit = 75\nThermal_Level = 1\n") == {
        "CPU_Speed_Limit": 75,
        "Thermal_Level": 1,
    }


def test_collector_returns_read_only_snapshot_and_sanitized_processes(tmp_path) -> None:
    collector = MacResourceCollector(
        runner=fixture_runner,
        repo_root=Path("/Users/test/scout-fusion"),
        disk_path=str(tmp_path),
    )

    snapshot = collector.snapshot()

    assert snapshot["schema_version"] == "scout.macos_resource_snapshot.v0.1"
    assert snapshot["boundary"] == {
        "read_only": True,
        "candidate_only": True,
        "runtime_safety_truth": False,
        "external_effects": False,
        "scope": "local macOS resource observation",
    }
    assert snapshot["cpu"]["active_percent"] == 40.0
    assert snapshot["memory"]["total_bytes"] == 8589934592
    assert snapshot["memory"]["available_bytes"] == (100 + 10 + 200) * 4096
    assert snapshot["memory"]["pressure"]["level"] == "normal"
    assert snapshot["power"]["battery_percent"] == 77
    assert snapshot["thermal"]["throttled"] is False
    assert snapshot["scout"]["status"] == "detected"
    assert snapshot["scout"]["process_count"] == 2
    assert snapshot["scout"]["processes"][0]["label"] == "phase4_admin_runtime"
    assert snapshot["scout"]["processes"][1]["label"] == "ollama"
    assert all("command" not in process for process in snapshot["scout"]["processes"])
    assert "SECRET_VALUE" not in str(snapshot)


def test_api_exposes_health_snapshot_and_static_page(tmp_path) -> None:
    collector = MacResourceCollector(
        runner=fixture_runner,
        repo_root=Path("/Users/test/scout-fusion"),
        disk_path=str(tmp_path),
    )
    client = TestClient(create_resource_monitor_app(collector=collector))

    health = client.get("/api/health")
    snapshot = client.get("/api/snapshot")
    page = client.get("/")

    assert health.status_code == 200
    assert health.json()["read_only"] is True
    assert snapshot.status_code == 200
    assert snapshot.json()["scout"]["process_count"] == 2
    assert page.status_code == 200
    assert "Scout / Mac Resource Observatory" in page.text
    assert "runtime safety truth" in page.text
