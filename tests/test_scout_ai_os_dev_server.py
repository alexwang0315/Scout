from __future__ import annotations

import json

from scout.cli.dev_server import build_dev_server_preflight, main


def test_dev_server_preflight_imports_real_app_and_required_routes() -> None:
    report = build_dev_server_preflight(host="0.0.0.0", port=9120)

    assert report["status"] == "ready"
    assert report["machine"]
    assert report["host"] == "0.0.0.0"
    assert report["port"] == 9120
    assert report["lan_exposed"] is True
    assert report["database"] == {"mode": "memory", "path_ref": ":memory:"}
    assert report["required_routes"] == ["/capabilities", "/requests"]
    assert report["missing_routes"] == []
    assert report["route_count"] >= 2
    assert report["boundary"] == {
        "starts_server": False,
        "loads_secret_values": False,
        "calls_external_model": False,
        "writes_database_file": False,
        "mutates_phase1_safety_truth": False,
        "sends_outbound": False,
        "controls_hardware": False,
    }


def test_dev_server_check_cli_prints_machine_readable_receipt(capsys) -> None:
    assert main(["--check", "--host", "127.0.0.1", "--port", "9120"]) == 0

    report = json.loads(capsys.readouterr().out)
    assert report["artifact_kind"] == "scout_ai_os_dev_server_preflight"
    assert report["schema_version"] == "scout.ai_os.dev_server_preflight.v1"
    assert report["status"] == "ready"
    assert report["lan_exposed"] is False
