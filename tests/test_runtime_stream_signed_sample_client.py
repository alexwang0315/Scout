from __future__ import annotations

import json
from pathlib import Path

from runtime_stream_signed_sample_client import (
    run_runtime_stream_signed_sample,
    run_runtime_stream_signed_sample_cli,
)


def _payload() -> dict[str, object]:
    return {
        "loggingTime": 1.0,
        "locationLatitude": "24.0",
        "locationLongitude": "121.0",
        "locationAltitude": "1200",
        "locationHorizontalAccuracy": "8.0",
        "pedometerDistance": 12.0,
        "pedometerNumberOfSteps": 18,
        "accelerometerAccelerationX": "0.1",
    }


def test_signed_sample_dry_run_builds_hashes_without_network_or_raw_payload() -> None:
    transport_calls = []

    result = run_runtime_stream_signed_sample(
        base_url="http://scout.local:9099/",
        payload=_payload(),
        secret_key="runtime-stream-secret-value",
        sequence_no=7,
        send=False,
        transport=lambda request: transport_calls.append(request),
    )
    serialized = result.to_json()

    assert result.status == "dry_run_ready"
    assert result.base_url == "http://scout.local:9099"
    assert result.network_send_attempted is False
    assert result.send_performed is False
    assert result.payload_sha256
    assert result.request_body_sha256
    assert result.envelope_id == "runtime_stream_signed_sample.0007"
    assert transport_calls == []
    assert "locationLatitude" not in serialized
    assert "24.0" not in serialized
    assert "runtime-stream-secret-value" not in serialized
    assert result.boundary.raw_payloads_embedded is False
    assert result.boundary.secret_values_embedded is False


def test_signed_sample_send_posts_signed_body_and_sanitizes_response() -> None:
    captured_requests = []
    response_body = json.dumps(
        {
            "status": "accepted",
            "ingest_surface": "runtime_stream_http_push",
            "transport_surface": "http_push",
            "observations_accepted": 1,
            "safety_level": "L0_NORMAL",
            "admission": {
                "status": "admitted_not_forwarded",
                "source_id": "runtime_source.apple_watch.v0",
            },
        },
        sort_keys=True,
    )

    def transport(request):
        captured_requests.append(request)
        return {"status_code": 200, "response_body": response_body}

    result = run_runtime_stream_signed_sample(
        base_url="http://127.0.0.1:9099",
        payload=_payload(),
        secret_key="runtime-stream-secret-value",
        send=True,
        transport=transport,
    )
    serialized = result.to_json()

    assert result.status == "sent"
    assert result.network_send_attempted is True
    assert result.send_performed is True
    assert result.http_status_code == 200
    assert result.response_status == "accepted"
    assert result.response_admission_status == "admitted_not_forwarded"
    assert result.response_transport_surface == "http_push"
    assert result.response_ingest_surface == "runtime_stream_http_push"
    assert result.response_admission_transport is None
    assert result.observations_accepted == 1
    assert result.safety_level == "L0_NORMAL"
    assert len(captured_requests) == 1
    assert captured_requests[0].endpoint_url.endswith(
        "/runtime/streams/http-push/observations"
    )
    assert captured_requests[0].body["payload"]["locationLatitude"] == "24.0"
    assert captured_requests[0].body["envelope"]["transport"] == "http_push"
    assert "locationLatitude" not in serialized
    assert "24.0" not in serialized
    assert "runtime-stream-secret-value" not in serialized


def test_signed_sample_cli_blocks_missing_secret_without_transport(
    tmp_path: Path,
) -> None:
    payload_path = tmp_path / "payload.json"
    output_path = tmp_path / "signed-sample-result.json"
    payload_path.write_text(json.dumps(_payload()), encoding="utf-8")
    transport_calls = []

    exit_code, result = run_runtime_stream_signed_sample_cli(
        [
            "--payload",
            str(payload_path),
            "--output",
            str(output_path),
            "--send",
        ],
        transport=lambda request: transport_calls.append(request),
    )
    serialized = output_path.read_text(encoding="utf-8")

    assert exit_code == 2
    assert result.status == "sample_blocked"
    assert result.blocker_reasons == ["missing_admission_secret"]
    assert result.network_send_attempted is False
    assert result.send_performed is False
    assert transport_calls == []
    assert "locationLatitude" not in serialized
