from __future__ import annotations

import json
from pathlib import Path

from runtime_stream_real_device_control_drill import (
    RealDeviceControlHttpRequest,
    run_real_device_control_drill,
    run_real_device_control_drill_cli,
)


def test_real_device_control_drill_dry_run_writes_planned_routes(tmp_path: Path) -> None:
    transport_calls = []

    result = run_real_device_control_drill(
        base_url="http://scout.local:9099/",
        operator_token="operator-token-value",
        evidence_dir=tmp_path,
        execute=False,
        transport=lambda request: transport_calls.append(request),
    )
    summary_path = tmp_path / "real-device-control-drill-summary.json"
    serialized = summary_path.read_text(encoding="utf-8")

    assert result.status == "dry_run_ready"
    assert result.base_url == "http://scout.local:9099"
    assert result.network_request_attempted is False
    assert result.stream_control_mutation_performed is False
    assert result.planned_route_count == 4
    assert result.planned_routes == [
        "GET /runtime/streams/control/status",
        "POST /runtime/streams/control/pause",
        "POST /runtime/streams/control/resume",
        "GET /runtime/streams/control/status",
    ]
    assert result.evidence_summary_path == str(summary_path)
    assert transport_calls == []
    assert "operator-token-value" not in serialized
    assert result.boundary.raw_payloads_embedded is False
    assert result.boundary.secret_values_embedded is False
    assert result.boundary.controls_device_hardware is False
    assert result.boundary.phase2_writeback_allowed is False


def test_real_device_control_drill_blocks_execution_without_operator_approval() -> None:
    transport_calls = []

    result = run_real_device_control_drill(
        base_url="http://127.0.0.1:9099",
        operator_token="operator-token-value",
        execute=True,
        operator_approve_control_drill=False,
        transport=lambda request: transport_calls.append(request),
    )

    assert result.status == "blocked"
    assert result.blocker_reasons == ["missing_explicit_operator_control_drill_approval"]
    assert result.network_request_attempted is False
    assert result.stream_control_mutation_performed is False
    assert transport_calls == []


def test_real_device_control_drill_executes_pause_resume_with_approval() -> None:
    captured: list[RealDeviceControlHttpRequest] = []

    def transport(request: RealDeviceControlHttpRequest) -> dict[str, object]:
        captured.append(request)
        if request.path == "/runtime/streams/control/status":
            return {
                "status_code": 200,
                "response_body": json.dumps(
                    {
                        "status": "observing",
                        "operator_authorization_required": True,
                        "token_value_exposed": False,
                    }
                ),
            }
        if request.path == "/runtime/streams/control/pause":
            return {
                "status_code": 200,
                "response_body": json.dumps({"snapshot_after": {"status": "paused"}}),
            }
        if request.path == "/runtime/streams/control/resume":
            return {
                "status_code": 200,
                "response_body": json.dumps({"snapshot_after": {"status": "observing"}}),
            }
        raise AssertionError(f"unexpected path {request.path}")

    result = run_real_device_control_drill(
        base_url="http://127.0.0.1:9099",
        operator_token="operator-token-value",
        execute=True,
        operator_approve_control_drill=True,
        transport=transport,
    )
    serialized = result.to_json()

    assert result.status == "passed"
    assert result.network_request_attempted is True
    assert result.stream_control_mutation_performed is True
    assert result.pre_control_status == "observing"
    assert result.pause_status_after == "paused"
    assert result.resume_status_after == "observing"
    assert result.final_control_status == "observing"
    assert result.final_status_restored is True
    assert [request.path for request in captured] == [
        "/runtime/streams/control/status",
        "/runtime/streams/control/pause",
        "/runtime/streams/control/resume",
        "/runtime/streams/control/status",
    ]
    assert all("Authorization" in request.headers for request in captured)
    assert "operator-token-value" not in serialized


def test_real_device_control_drill_cli_defaults_to_dry_run(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "evidence"
    token_file = tmp_path / "control-token"
    token_file.write_text("operator-token-value", encoding="utf-8")
    transport_calls = []

    exit_code, result = run_real_device_control_drill_cli(
        [
            "--operator-token-file",
            str(token_file),
            "--evidence-dir",
            str(evidence_dir),
        ],
        transport=lambda request: transport_calls.append(request),
    )

    assert exit_code == 0
    assert result.status == "dry_run_ready"
    assert result.network_request_attempted is False
    assert transport_calls == []
    assert (evidence_dir / "real-device-control-drill-summary.json").exists()
