"""Hailo snapshot/list API compatibility without actual device access."""
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json

from fastapi.testclient import TestClient
import pytest

import scout_hardware_monitor_api as api
from test_scout_hardware_monitor_api import sample as snapshot
from test_scout_hailo_monitor import sample as hailo_sample
from tools import scout_hailo_monitor as hailo


def test_hailo_status_history_legacy_null_stale_and_get_only(tmp_path, monkeypatch):
    monkeypatch.setattr(hailo, "collect_hailo", lambda *a, **k: pytest.fail("API may not sample Hailo"))
    fresh = snapshot()
    fresh["hailo"] = hailo_sample()
    old = snapshot(datetime.now(timezone.utc) - timedelta(minutes=2))
    unknown = copy.deepcopy(fresh)
    unknown["captured_at"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    unknown["hailo"]["captured_at"] = unknown["captured_at"]
    unknown["hailo"]["status"] = unknown["hailo"]["devices"][0]["status"] = "partial"
    unknown["hailo"]["devices"][0]["temperature_c"] = None
    (tmp_path / "status.json").write_text(json.dumps(fresh))
    (tmp_path / "history.jsonl").write_text("\n".join(json.dumps(s) for s in (old, unknown, fresh)) + "\n")
    events = {"captured_at": fresh["captured_at"], "events": ["Hailo 監控資料狀態改變：已讀取"]}
    (tmp_path / "events.jsonl").write_text(json.dumps(events) + "\n")
    def digest():
        return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in tmp_path.iterdir()}
    before = digest()
    with TestClient(api.create_hardware_monitor_app(state_dir=tmp_path), base_url="http://127.0.0.1") as client:
        current = client.get(api.PREFIX + "/status")
        assert current.status_code == 200
        h = current.json()["data"]["hailo"]
        assert h["status"] == "ok" and h["read_only"] is True
        assert h["devices"][0]["nnc_utilization_percent"] == 0
        assert h["devices"][0]["ram_used_bytes"] == 82 * 1024**2
        items = client.get(api.PREFIX + "/history?limit=60").json()["items"]
        assert len(items) == 3
        assert items[0]["hailo"] is None
        assert items[1]["hailo"]["devices"][0]["temperature_c"] is None
        assert items[2]["hailo"]["devices"][0]["temperature_c"] == 46.2
        assert client.get(api.PREFIX + "/events?limit=50").json()["items"][0]["events"] == events["events"]
        for method in ("post", "put", "patch", "delete"):
            assert getattr(client, method)(api.PREFIX + "/status").status_code == 405
        assert before == digest()
        spec = client.get("/openapi.json").json()
        assert "hailo" in spec["components"]["schemas"]["Snapshot"]["properties"]
        assert "hailo" not in spec["components"]["schemas"]["Snapshot"]["required"]
        assert "HailoDevice" in spec["components"]["schemas"]
        fresh["captured_at"] = (datetime.now(timezone.utc) - timedelta(seconds=151)).isoformat()
        fresh["hailo"]["captured_at"] = fresh["captured_at"]
        (tmp_path / "status.json").write_text(json.dumps(fresh))
        expired = client.get(api.PREFIX + "/status")
        assert expired.status_code == 503 and expired.json()["status"] == "stale"
        assert expired.json()["data"]["hailo"]["devices"][0]["temperature_c"] == 46.2


@pytest.mark.parametrize("problem", ["negative", "sentinel", "duplicate", "write", "false_ok"])
def test_malformed_hailo_is_typed_503_and_does_not_leak_private_data(tmp_path, problem):
    value = snapshot()
    value["hailo"] = hailo_sample()
    device = value["hailo"]["devices"][0]
    if problem == "negative":
        device["nnc_utilization_percent"] = -1
    elif problem == "sentinel":
        device["temperature_c"] = -1
    elif problem == "duplicate":
        value["hailo"]["devices"].append(copy.deepcopy(device))
    elif problem == "write":
        value["hailo"]["read_only"] = False
    else:
        device["voltage_mv"] = None
    (tmp_path / "status.json").write_text(json.dumps(value))
    with TestClient(api.create_hardware_monitor_app(state_dir=tmp_path), base_url="http://127.0.0.1") as client:
        response = client.get(api.PREFIX + "/status")
        assert response.status_code == 503
        assert response.json()["data"] is None and response.json()["freshness"]["state"] == "invalid"
        assert "private" not in response.text
