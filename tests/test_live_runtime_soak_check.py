from __future__ import annotations

import json
from pathlib import Path

from live_runtime_soak_check import (
    LiveRuntimeSoakHttpRequest,
    run_live_runtime_soak_check,
    run_live_runtime_soak_check_cli,
)


def test_live_runtime_soak_passes_with_read_only_get_samples_without_secret_leak() -> None:
    requests: list[LiveRuntimeSoakHttpRequest] = []

    def transport(request: LiveRuntimeSoakHttpRequest) -> dict[str, object]:
        requests.append(request)
        return {"status_code": 200, "response_body": json.dumps(_payload_for(request.path))}

    result = run_live_runtime_soak_check(
        base_url="http://scout.local:9099/",
        sample_count=2,
        interval_seconds=0,
        provider_control_token="operator-token-value",
        transport=transport,
        sleep=lambda _: None,
    )
    serialized = result.to_json()

    assert result.status == "passed"
    assert result.sample_count == 2
    assert len(result.samples) == 2
    assert result.samples[0].ok is True
    assert result.samples_all_ok is True
    assert result.runtime_profile == "pi-field-live"
    assert result.assistant_provider == "pydantic_ai"
    assert result.stream_control_status == "observing"
    assert result.provider_control_checked is True
    assert result.provider_control_allowed_actions == ["read_provider_status"]
    assert {request.method for request in requests} == {"GET"}
    assert {request.path for request in requests} == {
        "/health",
        "/assistant/status",
        "/runtime/streams/status-read-only",
        "/runtime/streams/control/status",
        "/providers/control/status",
    }
    assert all("/safety" not in request.path for request in requests)
    assert all("Authorization" in request.headers for request in requests if request.path == "/providers/control/status")
    assert "operator-token-value" not in serialized
    assert result.boundary.read_only_soak is True
    assert result.boundary.new_observations_sent is False
    assert result.boundary.stream_control_mutation_performed is False
    assert result.boundary.remote_provider_send_performed is False
    assert result.boundary.hardware_control_performed is False
    assert result.boundary.phase2_writeback_performed is False


def test_live_runtime_soak_fails_when_stream_boundary_allows_safety_mutation() -> None:
    def transport(request: LiveRuntimeSoakHttpRequest) -> dict[str, object]:
        payload = _payload_for(request.path)
        if request.path == "/runtime/streams/status-read-only":
            payload["boundary"]["safety_mutation_allowed"] = True
        return {"status_code": 200, "response_body": json.dumps(payload)}

    result = run_live_runtime_soak_check(
        base_url="http://scout.local:9099",
        sample_count=1,
        interval_seconds=0,
        provider_control_token="operator-token-value",
        transport=transport,
        sleep=lambda _: None,
    )

    assert result.status == "failed"
    assert result.samples_all_ok is False
    assert "sample_0:stream_safety_mutation_allowed" in result.blocker_reasons


def test_live_runtime_soak_cli_requires_provider_token_by_default(tmp_path: Path) -> None:
    output_path = tmp_path / "soak-result.json"
    transport_calls: list[LiveRuntimeSoakHttpRequest] = []

    exit_code, result = run_live_runtime_soak_check_cli(
        [
            "--sample-count",
            "1",
            "--interval-seconds",
            "0",
            "--output",
            str(output_path),
        ],
        transport=lambda request: transport_calls.append(request),
        sleep=lambda _: None,
    )

    assert exit_code == 2
    assert result.status == "failed"
    assert result.blocker_reasons == ["missing_provider_control_token"]
    assert transport_calls == []
    assert "missing_provider_control_token" in output_path.read_text(encoding="utf-8")


def test_live_runtime_soak_cli_writes_sanitized_summary_with_token_file(tmp_path: Path) -> None:
    token_path = tmp_path / "provider-token"
    output_path = tmp_path / "soak-result.json"
    token_path.write_text("operator-token-value", encoding="utf-8")

    def transport(request: LiveRuntimeSoakHttpRequest) -> dict[str, object]:
        return {"status_code": 200, "response_body": json.dumps(_payload_for(request.path))}

    exit_code, result = run_live_runtime_soak_check_cli(
        [
            "--sample-count",
            "1",
            "--interval-seconds",
            "0",
            "--provider-token-file",
            str(token_path),
            "--output",
            str(output_path),
        ],
        transport=transport,
        sleep=lambda _: None,
    )
    serialized = output_path.read_text(encoding="utf-8")

    assert exit_code == 0
    assert result.status == "passed"
    assert "operator-token-value" not in serialized
    assert '"read_only_soak": true' in serialized


def _payload_for(path: str) -> dict[str, object]:
    if path == "/health":
        return {
            "status": "ok",
            "runtime_profile": "pi-field-live",
            "optional_features": {
                "live_runtime_enabled": True,
                "runtime_stream_transport_enabled": True,
                "remote_provider_live_send_enabled": True,
                "hardware_provider_control_enabled": True,
            },
        }
    if path == "/assistant/status":
        return {
            "read_only": True,
            "model_interpretation": True,
            "provider": "pydantic_ai",
            "runtime_profile": "pi-field-live",
            "startup_connection_status": "connected:cloud",
            "active_profile": "cloud",
            "token_values_exposed": False,
            "local_fallback_enabled": True,
        }
    if path == "/runtime/streams/status-read-only":
        return {
            "status": "read_only_status_ready",
            "telemetry": {
                "status": "observing",
                "totals": {
                    "accepted_count": 4,
                    "rejected_count": 4,
                    "queued_count": 0,
                    "active_websocket_connections": 0,
                },
            },
            "boundary": {
                "read_only_surface": True,
                "transport_routes_mounted": True,
                "observation_ingest_allowed": True,
                "stream_control_mutation_allowed": True,
                "live_provider_send_allowed": True,
                "safety_mutation_allowed": False,
                "phase2_writeback_allowed": False,
                "raw_payloads_embedded": False,
            },
        }
    if path == "/runtime/streams/control/status":
        return {
            "status": "observing",
            "record_count": 3,
            "boundary": {
                "calls_safety_api": False,
                "controls_device_hardware": False,
                "remote_notifications_enabled": False,
                "phase2_writeback_count": 0,
            },
        }
    if path == "/providers/control/status":
        return {
            "status": "enabled",
            "policy_id": "hardware_control_policy.pi5_live.v0",
            "allowed_actions": ["read_provider_status"],
            "operator_authorization_required": True,
            "token_value_exposed": False,
            "safety_mutation_allowed": False,
            "outbound_send_allowed": False,
        }
    raise AssertionError(f"unexpected path: {path}")
