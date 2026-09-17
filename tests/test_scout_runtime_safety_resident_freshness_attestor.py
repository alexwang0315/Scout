from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scout_runtime_safety_resident_freshness_attestor import (
    FreshnessSourceSpec,
    evaluate_freshness_sources,
    run_freshness_attestor_cycles,
)


def _write(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


def test_freshness_attestor_accepts_current_and_rejects_stale_sources(
    tmp_path: Path,
) -> None:
    current = tmp_path / "cwa.json"
    stale = tmp_path / "gnss.json"
    _write(current, {"observed_at": "2026-08-31T03:55:00Z", "raw": "ignored"})
    _write(stale, {"selected_observed_at": "2026-06-16T02:18:30Z"})

    status = evaluate_freshness_sources(
        [
            FreshnessSourceSpec(
                source_id="cwa-live",
                source_ref="prod://qualification/cwa-live",
                artifact_path=current,
                timestamp_field="observed_at",
                max_age_minutes=180,
            ),
            FreshnessSourceSpec(
                source_id="gnss-observer",
                source_ref="pi://scout/gnss-observer",
                artifact_path=stale,
                timestamp_field="selected_observed_at",
                max_age_minutes=180,
            ),
        ],
        now=datetime(2026, 8, 31, 4, 0, tzinfo=timezone.utc),
    )

    encoded = json.dumps(status, sort_keys=True)
    assert status["status"] == "freshness_attestation_complete"
    assert status["current_source_count"] == 1
    assert status["stale_source_count"] == 1
    assert status["freshness_window_enforced"] is True
    assert status["stale_source_rejected"] is True
    assert status["sources"][0]["eligible"] is True
    assert status["sources"][1]["eligible"] is False
    assert "ignored" not in encoded
    assert '"raw"' not in encoded


def test_freshness_attestor_cycles_emit_resident_heartbeat_without_effects(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.json"
    output = tmp_path / "status.json"
    _write(source, {"observed_at": "2026-08-31T03:55:00Z"})
    times = iter(
        [
            datetime(2026, 8, 31, 4, 0, tzinfo=timezone.utc),
            datetime(2026, 8, 31, 4, 1, tzinfo=timezone.utc),
        ]
    )

    result = run_freshness_attestor_cycles(
        [
            FreshnessSourceSpec(
                source_id="cwa-live",
                source_ref="prod://qualification/cwa-live",
                artifact_path=source,
                timestamp_field="observed_at",
                max_age_minutes=180,
            )
        ],
        output_path=output,
        max_cycles=2,
        poll_seconds=0,
        now_factory=lambda: next(times),
        sleep=lambda _seconds: None,
    )

    persisted = json.loads(output.read_text(encoding="utf-8"))
    assert result["heartbeat_count"] == 2
    assert persisted["heartbeat_count"] == 2
    assert persisted["resident_process_observed"] is True
    assert persisted["runtime_safety_truth_mutated"] is False
    assert persisted["safety_api_called"] is False
    assert persisted["outbound_transport_invoked"] is False


def test_freshness_attestor_rejects_unsafe_source_contract(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="source_ref"):
        FreshnessSourceSpec(
            source_id="bad",
            source_ref="file:///tmp/raw.json",
            artifact_path=tmp_path / "raw.json",
            timestamp_field="observed_at",
        )
    with pytest.raises(ValueError, match="timestamp_field"):
        FreshnessSourceSpec(
            source_id="bad",
            source_ref="prod://qualification/bad",
            artifact_path=tmp_path / "raw.json",
            timestamp_field="payload.location.time",
        )
