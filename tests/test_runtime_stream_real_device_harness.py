from __future__ import annotations

import json
from pathlib import Path

from runtime_stream_real_device_harness import (
    run_real_device_stream_harness,
    run_real_device_stream_harness_cli,
)


def _payloads() -> list[dict[str, object]]:
    return [
        {
            "loggingTime": 1.0,
            "locationLatitude": "24.0",
            "locationLongitude": "121.0",
            "locationAltitude": "1200",
            "locationHorizontalAccuracy": "8.0",
            "pedometerDistance": 12.0,
            "pedometerNumberOfSteps": 18,
        },
        {
            "loggingTime": 1.1,
            "locationLatitude": "24.0001",
            "locationLongitude": "121.0001",
            "locationAltitude": "1201",
            "locationHorizontalAccuracy": "8.0",
            "pedometerDistance": 14.0,
            "pedometerNumberOfSteps": 20,
        },
    ]


def test_real_device_harness_dry_run_writes_summary_only_evidence(tmp_path: Path) -> None:
    transport_calls = []

    result = run_real_device_stream_harness(
        base_url="http://scout.local:9099/",
        payloads=_payloads(),
        secret_key="runtime-stream-secret-value",
        source_id="runtime_source.apple_watch.v0",
        source_kind="apple_watch",
        device_id="watch.alex.real.001",
        observed_at_start="2026-05-21T10:00:00+08:00",
        interval_ms=100,
        evidence_dir=tmp_path,
        send=False,
        transport=lambda request: transport_calls.append(request),
    )
    summary_path = tmp_path / "real-device-continuous-stream-summary.json"
    serialized = summary_path.read_text(encoding="utf-8")

    assert result.status == "dry_run_ready"
    assert result.payload_count == 2
    assert result.sequence_start == 1
    assert result.sequence_end == 2
    assert result.network_send_attempted is False
    assert result.send_performed is False
    assert result.explicit_operator_send_approval is False
    assert result.evidence_summary_path == str(summary_path)
    assert len(result.payload_sha256s) == 2
    assert len(result.request_body_sha256s) == 2
    assert len(result.dedupe_keys) == 2
    assert transport_calls == []
    assert "locationLatitude" not in serialized
    assert "24.0" not in serialized
    assert "runtime-stream-secret-value" not in serialized
    assert result.boundary.raw_payloads_embedded is False
    assert result.boundary.secret_values_embedded is False
    assert result.boundary.incident_bridge_enable_allowed is False
    assert result.boundary.phase2_writeback_allowed is False


def test_real_device_harness_blocks_send_without_operator_approval() -> None:
    transport_calls = []

    result = run_real_device_stream_harness(
        base_url="http://127.0.0.1:9099",
        payloads=_payloads(),
        secret_key="runtime-stream-secret-value",
        device_id="watch.alex.real.001",
        send=True,
        operator_approve_live_send=False,
        transport=lambda request: transport_calls.append(request),
    )

    assert result.status == "blocked"
    assert result.blocker_reasons == ["missing_explicit_operator_live_send_approval"]
    assert result.network_send_attempted is False
    assert result.send_performed is False
    assert transport_calls == []


def test_real_device_harness_send_uses_explicit_operator_approval_and_sanitizes() -> None:
    captured_requests = []
    response_body = json.dumps(
        {
            "status": "accepted",
            "ingest_surface": "runtime_stream_http_push",
            "transport_surface": "http_push",
            "observations_accepted": 1,
            "safety_level": "L0_NORMAL",
            "admission": {"status": "admitted_not_forwarded"},
        },
        sort_keys=True,
    )

    def transport(request):
        captured_requests.append(request)
        return {"status_code": 200, "response_body": response_body}

    result = run_real_device_stream_harness(
        base_url="http://127.0.0.1:9099",
        payloads=_payloads(),
        secret_key="runtime-stream-secret-value",
        device_id="watch.alex.real.001",
        send=True,
        operator_approve_live_send=True,
        transport=transport,
    )
    serialized = result.to_json()

    assert result.status == "sent"
    assert result.network_send_attempted is True
    assert result.send_performed is True
    assert result.explicit_operator_send_approval is True
    assert result.sent_count == 2
    assert result.transport_error_count == 0
    assert len(captured_requests) == 2
    assert captured_requests[0].body["payload"]["locationLatitude"] == "24.0"
    assert "locationLatitude" not in serialized
    assert "24.0" not in serialized
    assert "runtime-stream-secret-value" not in serialized


def test_real_device_harness_cli_defaults_to_dry_run(tmp_path: Path) -> None:
    payloads_path = tmp_path / "payloads.json"
    evidence_dir = tmp_path / "evidence"
    payloads_path.write_text(json.dumps(_payloads()), encoding="utf-8")
    transport_calls = []

    exit_code, result = run_real_device_stream_harness_cli(
        [
            "--payloads",
            str(payloads_path),
            "--secret",
            "runtime-stream-secret-value",
            "--evidence-dir",
            str(evidence_dir),
        ],
        transport=lambda request: transport_calls.append(request),
    )

    assert exit_code == 0
    assert result.status == "dry_run_ready"
    assert result.network_send_attempted is False
    assert result.send_performed is False
    assert transport_calls == []
    assert (evidence_dir / "real-device-continuous-stream-summary.json").exists()


def test_real_device_harness_cli_honors_replay_timing_only_when_sending(
    tmp_path: Path,
) -> None:
    payloads_path = tmp_path / "payloads.json"
    payloads_path.write_text(
        json.dumps(
            {
                "artifact_kind": "runtime_stream_replay_payload_batch",
                "replay_timing": {
                    "timing_source": "prerecorded_observed_at",
                    "replay_speed_multiplier": 2.0,
                    "send_delays_ms": [0, 1250],
                },
                "payloads": _payloads(),
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    captured_requests = []
    sleep_calls = []
    response_body = json.dumps(
        {
            "status": "accepted",
            "ingest_surface": "runtime_stream_http_push",
            "transport_surface": "http_push",
            "observations_accepted": 1,
            "safety_level": "L0_NORMAL",
            "admission": {"status": "admitted_not_forwarded"},
        },
        sort_keys=True,
    )

    def transport(request):
        captured_requests.append(request)
        return {"status_code": 200, "response_body": response_body}

    exit_code, result = run_real_device_stream_harness_cli(
        [
            "--payloads",
            str(payloads_path),
            "--secret",
            "runtime-stream-secret-value",
            "--send",
            "--operator-approve-live-send",
        ],
        transport=transport,
        sleep=lambda seconds: sleep_calls.append(seconds),
    )

    assert exit_code == 0
    assert result.status == "sent"
    assert result.replay_timing_source == "prerecorded_observed_at"
    assert result.replay_speed_multiplier == 2.0
    assert result.send_delay_count == 2
    assert result.send_delays_ms == [0, 1250]
    assert result.total_send_delay_ms == 1250
    assert sleep_calls == [1.25]
    assert len(captured_requests) == 2


def test_real_device_harness_clamps_replay_timing_to_10hz() -> None:
    captured_requests = []
    sleep_calls = []
    response_body = json.dumps(
        {
            "status": "accepted",
            "ingest_surface": "runtime_stream_http_push",
            "transport_surface": "http_push",
            "observations_accepted": 1,
            "safety_level": "L0_NORMAL",
            "admission": {"status": "admitted_not_forwarded"},
        },
        sort_keys=True,
    )

    def transport(request):
        captured_requests.append(request)
        return {"status_code": 200, "response_body": response_body}

    result = run_real_device_stream_harness(
        base_url="http://127.0.0.1:9099",
        payloads=_payloads(),
        secret_key="runtime-stream-secret-value",
        device_id="watch.alex.real.001",
        send=True,
        operator_approve_live_send=True,
        send_delays_ms=[0, 50],
        replay_timing_source="prerecorded_observed_at",
        replay_speed_multiplier=3.0,
        transport=transport,
        sleep=lambda seconds: sleep_calls.append(seconds),
    )

    assert result.status == "sent"
    assert result.send_delays_ms == [0, 100]
    assert result.total_send_delay_ms == 100
    assert sleep_calls == [0.1]
    assert len(captured_requests) == 2
