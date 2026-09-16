"""No hardware or network: parser fixtures and owned fake subprocesses only."""
import copy
from datetime import datetime, timezone
import json
import subprocess
import sys

import pytest
from pydantic import ValidationError

import scout_hardware_monitor_api as api
from tools import scout_hailo_monitor as hailo
from tools import scout_hardware_monitor as monitor


ID = "pci/0001:03:00.0"
HEADER = ("Device ID Architecture NNC Utilization (%) CPU Utilization (%) RAM Utilization (%) "
          "RAM Usage (MB) On Die Temperature (C) On Die Voltage (mV)\n")
ROW = ID + " HAILO10H 0.0 0.2 1.1 82 / 7221 46.2 802\n"


def inventory(ids=(ID,)):
    return {"sections": {"pcie": {"status": "ok", "items": [
        {"id": value.removeprefix("pci/"), "driver": "hailo1x", "properties": {"vendor": "0x1e60"}}
        for value in ids]}}}


def sample():
    return {"captured_at": datetime.now(timezone.utc).isoformat(), "status": "ok", "source": "hailortcli.monitor",
            "sample_window_ms": 1000, "read_only": True,
            "devices": list(hailo.parse_monitor_table((HEADER + ROW).encode()).values()), "errors": []}


def test_cli_binary_megabytes_and_zero_are_not_unknown():
    device = hailo.parse_monitor_table(("\x1b[H\x1b[J" + HEADER + ROW).encode())[ID]
    assert device["nnc_utilization_percent"] == 0
    assert device["ram_used_bytes"] == 82 * 1024**2
    assert device["ram_total_bytes"] == 7221 * 1024**2
    assert device["temperature_c"] == 46.2
    assert device["voltage_mv"] == 802
    assert device["status"] == "ok" and device["errors"] == []
    api.HailoTelemetry.model_validate(sample())


@pytest.mark.parametrize("token", ["N/A", "-1", "-1.0", "NaN", "inf", "101", "broken"])
def test_bad_utilization_remains_null_and_does_not_hide_health(token):
    device = hailo.parse_monitor_table((HEADER + ROW.replace("0.0 0.2", token + " 0.2")).encode())[ID]
    assert device["nnc_utilization_percent"] is None
    assert device["temperature_c"] == 46.2
    assert device["status"] == "partial"


def test_null_ram_and_all_unknown_are_not_zero():
    row = ID + " HAILO10H N/A N/A N/A N/A N/A N/A\n"
    device = hailo.parse_monitor_table((HEADER + row).encode())[ID]
    assert device["status"] == "unavailable"
    assert all(device[key] is None for key in hailo.METRICS)
    api.HailoDevice.model_validate(device)


def test_multiple_devices_do_not_merge_or_mix_later_table():
    other = "pci/0001:05:00.0"
    rows = hailo.parse_monitor_table((HEADER + ROW + ROW.replace(ID, other).replace("46.2", "50.1")
                                    + HEADER + ROW.replace("46.2", "99.0")).encode())
    assert set(rows) == {ID, other}
    assert rows[ID]["temperature_c"] == 46.2
    assert rows[other]["temperature_c"] == 50.1
    duplicate = hailo.parse_monitor_table((HEADER + ROW + ROW).encode())[ID]
    assert duplicate["status"] == "unavailable"


@pytest.mark.parametrize("body", [ROW, HEADER + ROW.rstrip("\n"), HEADER + ROW.replace(ID, "$(touch /tmp/no)")])
def test_unframed_incomplete_and_untrusted_device_ids_are_rejected(body):
    assert hailo.parse_monitor_table(body.encode()) == {}


def fake_child(monkeypatch, body):
    real = subprocess.Popen
    children = []
    def spawn(command, **kwargs):
        assert command == ("/usr/bin/hailortcli", "monitor")
        assert kwargs["shell"] is False
        process = real([sys.executable, "-c", body], **kwargs)
        children.append(process)
        return process
    monkeypatch.setattr(hailo.subprocess, "Popen", spawn)
    return children


def test_owned_process_stops_after_first_frame_and_is_reaped(monkeypatch):
    children = fake_child(monkeypatch,
        "import os,time; os.write(2,b'x'*2048); os.write(1," + repr((HEADER + ROW).encode()) + "); time.sleep(60)")
    result = hailo.collect_hailo(inventory(), timeout=3)
    assert result["status"] == "ok"
    assert result["devices"][0]["temperature_c"] == 46.2
    assert len(children) == 1 and children[0].poll() is not None
    assert children[0].stdout.closed and children[0].stderr.closed


def test_timeout_keeps_unknown_and_next_request_recovers(monkeypatch):
    children = fake_child(monkeypatch, "import signal,time; signal.signal(signal.SIGINT,signal.SIG_IGN); time.sleep(60)")
    failed = hailo.collect_hailo(inventory(), timeout=0.2)
    assert failed["status"] == "unavailable" and failed["errors"] == ["timeout"]
    assert all(failed["devices"][0][key] is None for key in hailo.METRICS)
    assert children[0].poll() is not None
    monkeypatch.undo()
    recovered_children = fake_child(monkeypatch, "import os,time; os.write(1," + repr((HEADER + ROW).encode()) + "); time.sleep(60)")
    assert hailo.collect_hailo(inventory(), timeout=3)["status"] == "ok"
    assert recovered_children[0].poll() is not None


def test_empty_enumeration_does_not_run_cli_but_unknown_inventory_is_not_absent(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("no Hailo command expected")
    monkeypatch.setattr(hailo.subprocess, "Popen", forbidden)
    result = hailo.collect_hailo(inventory(()))
    assert result["status"] == "ok" and result["devices"] == []
    result = hailo.collect_hailo({})
    assert result["status"] == "unavailable" and result["errors"] == ["inventory_unavailable"]


def test_cli_missing_and_output_bounds_return_fixed_public_error_codes(monkeypatch):
    def missing(*args, **kwargs):
        raise FileNotFoundError("private path")
    monkeypatch.setattr(hailo.subprocess, "Popen", missing)
    result = hailo.collect_hailo(inventory())
    assert result["errors"] == ["cli_unavailable"] and "private" not in json.dumps(result)
    monkeypatch.undo()
    children = fake_child(monkeypatch, "import os,time; os.write(1,b'x'*150000); time.sleep(60)")
    assert hailo.collect_hailo(inventory(), timeout=3)["errors"] == ["output_too_large"]
    assert children[0].poll() is not None


@pytest.mark.parametrize("key,value", [("nnc_utilization_percent", True), ("cpu_utilization_percent", 101),
    ("ram_used_bytes", -1), ("ram_total_bytes", 0), ("ram_used_bytes", 2**50),
    ("temperature_c", float("nan")), ("temperature_c", -1), ("voltage_mv", -1),
    ("status", "unavailable")])
def test_api_rejects_invalid_or_false_status(key, value):
    current = sample()
    current["devices"][0][key] = value
    with pytest.raises(ValidationError):
        api.HailoTelemetry.model_validate(current)


def test_api_allows_partial_but_rejects_duplicates_and_unsafe_effect_flags():
    current = sample()
    current["status"] = current["devices"][0]["status"] = "partial"
    current["devices"][0]["temperature_c"] = None
    api.HailoTelemetry.model_validate(current)
    current["devices"].append(copy.deepcopy(current["devices"][0]))
    with pytest.raises(ValidationError):
        api.HailoTelemetry.model_validate(current)
    current = sample()
    current["read_only"] = False
    with pytest.raises(ValidationError):
        api.HailoTelemetry.model_validate(current)


def test_hailo_events_are_not_notifications_or_health_thresholds(tmp_path, monkeypatch):
    from test_scout_hardware_monitor import snapshot
    previous = snapshot(tmp_path)
    previous.update(hailo=sample(), alerts={}, status="ok", pending_notifications=[])
    old = copy.deepcopy(previous)
    previous["hailo"]["devices"][0] = hailo.unknown_device(ID, "timeout")
    previous["hailo"]["status"] = "unavailable"
    (tmp_path / "status.json").write_text(json.dumps(old))
    monkeypatch.setattr(monitor, "collect", lambda *args: previous)
    monkeypatch.setattr(monitor, "notify_mac", lambda *args: pytest.fail("Hailo cannot add notifications"))
    current = monitor.run_once(tmp_path, tmp_path / "ignored", notify=True)
    assert current["pending_notifications"] == [] and current["notification"]["status"] == "quiet"
    assert "hailo" not in current["alerts"]
    event = json.loads((tmp_path / "events.jsonl").read_text().splitlines()[-1])
    assert event["captured_at"] == current["captured_at"]
    assert any("Hailo" in text for text in event["events"])
    assert json.loads((tmp_path / "history.jsonl").read_text().splitlines()[-1])["hailo"]["status"] == "unavailable"
    assert hailo.hailo_transitions(current, {}) == []
