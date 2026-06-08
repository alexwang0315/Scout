from __future__ import annotations

import json
from pathlib import Path

from runtime_stream_real_device_policy_drill import (
    run_real_device_policy_drill,
    run_real_device_policy_drill_cli,
)


def _payload() -> dict[str, object]:
    return {
        "timestamp": 60.0,
        "source": "apple_watch",
        "lat": 24.0,
        "lon": 121.0,
        "elevation_m": 1001.0,
        "gps_horizontal_accuracy_m": 8.0,
    }


def test_real_device_policy_drill_writes_backpressure_offline_latest_summary(
    tmp_path: Path,
) -> None:
    result = run_real_device_policy_drill(
        payload=_payload(),
        secret_key="runtime-stream-secret-value",
        evidence_dir=tmp_path,
        device_id="watch.alex.real.001",
    )
    summary_path = tmp_path / "real-device-policy-drill-summary.json"
    serialized = summary_path.read_text(encoding="utf-8")

    assert result.status == "passed"
    assert result.evidence_summary_path == str(summary_path)
    assert result.device_identity_matched is True
    assert result.sequence_start == 1
    assert result.sequence_end == 4
    assert result.admitted_count == 1
    assert result.backpressure_count == 1
    assert result.disconnected_queue_count == 1
    assert result.latest_point_retained_count == 1
    assert result.safety_api_call_count == 0
    assert result.runtime_forward_count == 0
    assert result.phase2_writeback_count == 0
    assert result.raw_payloads_embedded is False
    assert result.secret_values_embedded is False
    assert [decision.status for decision in result.decisions] == [
        "admitted_not_forwarded",
        "queued_backpressure",
        "queued_disconnected",
        "latest_point_retained",
    ]
    assert '"lat"' not in serialized
    assert "24.0" not in serialized
    assert "runtime-stream-secret-value" not in serialized


def test_real_device_policy_drill_blocks_missing_secret_without_safety_call() -> None:
    result = run_real_device_policy_drill(
        payload=_payload(),
        secret_key=None,
        device_id="watch.alex.real.001",
    )

    assert result.status == "blocked"
    assert result.blocker_reasons == ["missing_admission_secret"]
    assert result.safety_api_call_count == 0
    assert result.runtime_forward_count == 0
    assert result.decisions == []


def test_real_device_policy_drill_cli_writes_summary(tmp_path: Path) -> None:
    payload_path = tmp_path / "payload.json"
    evidence_dir = tmp_path / "evidence"
    payload_path.write_text(json.dumps(_payload()), encoding="utf-8")

    exit_code, result = run_real_device_policy_drill_cli(
        [
            "--payload",
            str(payload_path),
            "--secret",
            "runtime-stream-secret-value",
            "--evidence-dir",
            str(evidence_dir),
            "--device-id",
            "watch.alex.real.001",
        ]
    )

    assert exit_code == 0
    assert result.status == "passed"
    assert (evidence_dir / "real-device-policy-drill-summary.json").exists()
