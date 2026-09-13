from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

import scout_hardware_monitor_api as api


def sample(now=None):
    now = now or datetime.now(timezone.utc)
    return {
        "captured_at": now.isoformat(), "host": "scout", "status": "ok", "uptime_seconds": 600,
        "cpu_count": 4, "cpu_used_percent": None, "load_average": [0.2, 0.1, 0.1],
        "power": {"status": "ok", "source": "/private/observer/path", "captured_at": now.isoformat(),
                  "age_seconds": 0.5, "battery_percent": 81, "flow": "charging", "battery_power_w": 19.2,
                  "battery_voltage_mv": 16000, "battery_current_ma": 1200, "ext5v_v": 5.2,
                  "cell_voltage_mv": [4000] * 4, "active_throttle_bits": 0},
        "memory": {"total_bytes": 8000, "used_bytes": 2000, "available_bytes": 6000,
                   "used_percent": 25, "swap_total_bytes": 2000, "swap_used_bytes": 0},
        "disks": [{"mount": "/", "device": "/dev/nvme0n1p2", "total_bytes": 10000,
                   "used_bytes": 2000, "available_bytes": 8000, "used_percent": 20, "read_only": False}],
        "sensors": [{"name": "cpu_thermal", "source": "/sys/class/hwmon/hwmon0/temp1_input", "temperature_c": 44.6}],
        "alerts": {}, "errors": {}, "thresholds": {"battery_percent": {"warning": 20, "critical": 10}, "ups_stale_seconds": 15},
        "pending_notifications": ["private notification"], "boot_id": "private boot id", "cpu_ticks": {},
        "notification": {"host": "private-host"},
    }


@pytest.fixture
def client(tmp_path):
    with TestClient(api.create_hardware_monitor_app(state_dir=tmp_path), base_url="http://127.0.0.1") as value:
        yield value


def save(tmp_path, value):
    (tmp_path / "status.json").write_text(json.dumps(value))


def test_latest_snapshot_is_read_only_and_omits_internal_state(client, tmp_path):
    save(tmp_path, sample())
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in tmp_path.iterdir()}
    response = client.get(api.PREFIX + "/status")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["freshness"]["state"] == "fresh"
    assert body["freshness"]["sample_interval_seconds"] == 60
    assert body["data"]["power"]["battery_percent"] == 81
    assert body["data"]["cpu_used_percent"] is None
    assert "private" not in response.text
    assert "boot_id" not in body["data"]
    assert response.headers["cache-control"] == "no-store"
    assert before == {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in tmp_path.iterdir()}


@pytest.mark.parametrize("problem", ["missing", "broken", "wrong_shape", "future", "naive", "missing_power", "too_large"])
def test_unusable_snapshots_return_typed_503_without_internal_errors(client, tmp_path, problem):
    raw = sample()
    if problem == "future":
        raw["captured_at"] = (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()
    elif problem == "naive":
        raw["captured_at"] = "2026-09-11T00:00:00"
    elif problem == "missing_power":
        raw["power"] = {"status": "ok"}
    elif problem == "wrong_shape":
        raw = []
    if problem != "missing":
        save(tmp_path, raw)
    if problem == "broken":
        (tmp_path / "status.json").write_text("{")
    elif problem == "too_large":
        (tmp_path / "status.json").write_bytes(b" " * (api.MAX_SNAPSHOT_BYTES + 1))
    response = client.get(api.PREFIX + "/status")
    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"
    assert response.json()["data"] is None
    assert response.headers["retry-after"] == "60"
    assert str(tmp_path) not in response.text


def test_stale_503_preserves_last_sample_and_critical_is_200(client, tmp_path):
    raw = sample(datetime.now(timezone.utc) - timedelta(seconds=151))
    save(tmp_path, raw)
    response = client.get(api.PREFIX + "/status")
    assert response.status_code == 503
    assert response.json()["status"] == "stale"
    assert response.json()["data"]["power"]["battery_percent"] == 81
    raw = sample()
    raw["status"] = "critical"
    raw["alerts"] = {"battery": {"severity": "critical", "message": "電池過低"}}
    save(tmp_path, raw)
    assert client.get(api.PREFIX + "/status").status_code == 200
    assert client.get(api.PREFIX + "/status").json()["status"] == "critical"


def test_rotation_history_order_partial_append_and_invalid_record(client, tmp_path):
    now = datetime.now(timezone.utc)
    records = [sample(now - timedelta(minutes=i)) for i in range(5)]
    (tmp_path / "history.jsonl").write_text(json.dumps(records[1]) + "\ninvalid\n" + json.dumps(records[0]) + '\n{"unfinished":')
    (tmp_path / "history.jsonl.1").write_text("\n".join(json.dumps(s) for s in reversed(records[2:])) + "\n")
    response = client.get(api.PREFIX + "/history?limit=3")
    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "partial"
    assert body["meta"]["has_more"] is True
    assert body["meta"]["skipped_invalid_records"] == 1
    times = [datetime.fromisoformat(s["captured_at"]) for s in body["items"]]
    assert times == sorted(datetime.fromisoformat(s["captured_at"]) for s in records[:3])
    assert "private notification" not in response.text


def test_empty_events_and_limit_validation(client, tmp_path):
    assert client.get(api.PREFIX + "/events").json()["items"] == []
    for query in ("limit=0", "limit=201", "limit=bad", "limit=-1"):
        assert client.get(api.PREFIX + "/events?" + query).status_code == 422
    assert client.get(api.PREFIX + "/history?limit=1441").status_code == 422
    event = {"captured_at": datetime.now(timezone.utc).isoformat(), "events": ["已恢復：記憶體警告"]}
    (tmp_path / "events.jsonl").write_text(json.dumps(event) + "\n")
    assert client.get(api.PREFIX + "/events").json()["items"][0]["events"] == event["events"]


def test_read_budget_is_reported_as_partial(client, tmp_path, monkeypatch):
    event = {"captured_at": datetime.now(timezone.utc).isoformat(), "events": ["test"]}
    (tmp_path / "events.jsonl").write_text((json.dumps(event) + "\n") * 10)
    monkeypatch.setattr(api, "MAX_HISTORY_BYTES", 150)
    body = client.get(api.PREFIX + "/events").json()
    assert body["status"] == "partial"
    assert body["meta"]["scan_truncated"] is True


def test_no_write_routes_file_serving_or_wildcard_cors(client, tmp_path):
    save(tmp_path, sample())
    for method in ("post", "put", "patch", "delete"):
        assert getattr(client, method)(api.PREFIX + "/status").status_code == 405
    assert client.get("/status.json").status_code == 404
    assert client.get("/../../etc/passwd").status_code == 404
    assert client.get(api.PREFIX + "/status", headers={"Host": "attacker.example"}).status_code == 400
    response = client.get(api.PREFIX + "/status", headers={"Origin": "https://attacker.example"})
    assert "access-control-allow-origin" not in response.headers
    spec = client.get("/openapi.json").json()
    assert set(spec["paths"]) == {api.PREFIX + suffix for suffix in ("/status", "/history", "/events")} | {"/healthz"}
    assert spec["paths"][api.PREFIX + "/status"]["get"]["responses"]["503"]["content"]["application/json"]["schema"]["$ref"].endswith("StatusResponse")


def test_router_can_mount_in_dashboard_without_loading_its_runtime(tmp_path):
    save(tmp_path, sample())
    app = FastAPI()
    app.include_router(api.create_hardware_monitor_router(state_dir=tmp_path))
    with TestClient(app) as client:
        assert client.get(api.PREFIX + "/status").json()["data"]["host"] == "scout"


def test_partial_power_preserves_supply_in_status_history_and_stale_503(client, tmp_path):
    raw = sample()
    raw["status"] = "warning"
    raw["power"] = {"status": "unavailable", "ups_status": "unavailable", "supply_status": "ok",
                    "captured_at": raw["captured_at"], "age_seconds": 0.2,
                    "ups_error_code": "communication_error", "supply_error_code": None,
                    "ext5v_v": 5.18, "active_throttle_bits": 0, "historical_throttle_bits": 0,
                    "error": "/private/observer/error"}
    raw["alerts"] = {"power_telemetry": {"severity": "warning", "message": "UPS 通訊失敗（I²C）"}}
    save(tmp_path, raw)
    (tmp_path / "history.jsonl").write_text(json.dumps(raw) + "\n")
    response = client.get(api.PREFIX + "/status")
    assert response.status_code == 200
    power = response.json()["data"]["power"]
    assert power["ext5v_v"] == 5.18
    assert power["battery_percent"] is None
    assert power["ups_error_code"] == "communication_error"
    assert power["ups_status"] == "unavailable" and power["supply_status"] == "ok"
    assert "/private" not in response.text
    assert client.get(api.PREFIX + "/history").json()["items"][0]["power"] == power
    raw["captured_at"] = (datetime.now(timezone.utc) - timedelta(seconds=151)).isoformat()
    save(tmp_path, raw)
    response = client.get(api.PREFIX + "/status")
    assert response.status_code == 503
    assert response.json()["status"] == "stale"
    assert response.json()["data"]["power"] == power


@pytest.mark.parametrize("bad", ["healthy_overall", "missing_supply_value", "false_ups_value", "unsafe_error"])
def test_split_power_contract_rejects_inconsistent_or_unsafe_claims(client, tmp_path, bad):
    raw = sample()
    raw["power"].update(ups_status="ok", supply_status="ok")
    if bad == "healthy_overall":
        raw["power"]["supply_status"] = "unavailable"
    elif bad == "missing_supply_value":
        raw["power"]["ext5v_v"] = None
    elif bad == "false_ups_value":
        raw["power"].update(status="unavailable", ups_status="unavailable")
    else:
        raw["power"]["ups_error_code"] = "<img src=x onerror=bad> /private/path"
    save(tmp_path, raw)
    response = client.get(api.PREFIX + "/status")
    assert response.status_code == 503
    assert response.json()["data"] is None
    assert "/private" not in response.text


def test_legacy_power_remains_compatible_without_component_status(client, tmp_path):
    raw = sample()
    save(tmp_path, raw)
    body = client.get(api.PREFIX + "/status").json()
    assert body["data"]["power"]["ups_status"] is None
    assert body["data"]["power"]["supply_status"] is None
    assert body["data"]["power"]["battery_percent"] == 81


def test_api_installer_starts_sampler_and_timer_before_api(tmp_path):
    script = Path(__file__).resolve().parents[1] / "scripts/install-scout-hardware-monitor-api.py"
    command = [sys.executable, str(script), "--render-only", str(tmp_path)]
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    text = (tmp_path / "scout-hardware-monitor-api.service").read_text()
    assert "api.py" in text
    assert "Wants=scout-hardware-monitor.service scout-hardware-monitor.timer" in text
    assert "After=scout-hardware-monitor.service" in text
    assert "--static-dir" in text
    assert "Restart=on-failure" in text
    assert "WantedBy=default.target" in text
    assert subprocess.run(command, capture_output=True).returncode != 0


def test_hardware_overview_assets_are_served_with_no_directory_browsing(client):
    assert client.get("/monitor").status_code == 200
    assert "硬體與連線" in client.get("/").text
    assert client.get("/monitor/app.js").status_code == 200
    assert client.get("/monitor/style.css").status_code == 200
    assert client.get("/monitor/../../scout_hardware_monitor_api.py").status_code == 404


def test_inventory_fields_are_additive_and_gpio_values_cannot_claim_sampling(client, tmp_path):
    raw = sample()
    raw["inventory"] = {"captured_at": raw["captured_at"], "status": "ok", "sections": {
        "gpio": {"status": "ok", "summary": "1 chip", "notes": [], "errors": [], "items": [
            {"id": "gpiochip0", "name": "pinctrl-rp1", "state": "present", "properties": {"line_count": 1},
             "lines": [{"offset": 5, "name": "GPIO5", "direction": "output", "consumer": "lg", "active_low": False, "value": None}]}]}}}
    save(tmp_path, raw)
    body = client.get(api.PREFIX + "/status").json()
    assert body["data"]["inventory"]["sections"]["gpio"]["items"][0]["lines"][0]["value"] is None
    raw["inventory"]["gpio_value_sampling_performed"] = True
    save(tmp_path, raw)
    assert client.get(api.PREFIX + "/status").status_code == 503
