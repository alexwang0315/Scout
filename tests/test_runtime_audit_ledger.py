from __future__ import annotations

import json
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from runtime_audit_ledger import FileRuntimeAuditLedger
from runtime_audit_models import RuntimeAuditRecordInput


class Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 8, 7, 3, 0, tzinfo=timezone.utc)

    def now(self) -> datetime:
        current = self.value
        self.value += timedelta(milliseconds=25)
        return current


def _record(**overrides: object) -> RuntimeAuditRecordInput:
    values: dict[str, object] = {
        "event_type": "workspace.io.completed",
        "outcome": "succeeded",
        "severity": "info",
        "category": "workspace",
        "subcategory": "artifact-write",
        "module": "runtime-audit-ledger",
        "feature": "runtime-audit",
        "operation": "write-artifact",
        "summary": "Workspace artifact persisted",
        "workspace_id": "trip_001",
        "artifact_kind": "route_projection",
        "artifact_ref_hash": "a" * 64,
        "record_count": 3,
        "byte_count": 128,
    }
    values.update(overrides)
    return RuntimeAuditRecordInput.model_validate(values)


def test_runtime_audit_model_is_typed_and_rejects_arbitrary_payload() -> None:
    record = _record()

    assert record.telemetry_only is True
    assert record.runtime_safety_truth is False
    with pytest.raises(ValidationError):
        RuntimeAuditRecordInput.model_validate(
            {
                **record.model_dump(mode="json"),
                "payload": {"raw_gpx": "forbidden"},
            }
        )


def test_file_ledger_is_append_only_hash_chained_rotated_and_queryable(
    tmp_path: Path,
) -> None:
    clock = Clock()
    ledger = FileRuntimeAuditLedger(
        root=tmp_path / "audit",
        runtime_instance_id="runtime-test-001",
        now_factory=clock.now,
        max_events_per_file=2,
    )

    started = ledger.start(
        application="scout-dashboard",
        runtime_profile="test",
        workspace_id="trip_001",
    )
    written = ledger.append(_record())
    failed = ledger.append(
        _record(
            event_type="provider.call.completed",
            outcome="failed",
            severity="error",
            category="provider",
            subcategory="weather",
            module="weather.client",
            feature="cwa-rainfall",
            operation="fetch-grid",
            summary="Provider call failed safely",
            provider="cwa",
            error_code="timeout",
            artifact_kind=None,
            artifact_ref_hash=None,
            record_count=None,
            byte_count=None,
        )
    )
    ended = ledger.stop(reason="clean_shutdown")

    assert [started.sequence, written.sequence, failed.sequence, ended.sequence] == [
        1,
        2,
        3,
        4,
    ]
    assert started.previous_event_hash is None
    assert written.previous_event_hash == started.event_hash
    assert failed.previous_event_hash == written.event_hash
    assert ended.previous_event_hash == failed.event_hash
    assert len(list(ledger.instance_dir.glob("events-*.jsonl"))) == 2
    assert ledger.verify_integrity().verified is True

    response = ledger.query(event_type="provider.call.completed", limit=20)
    assert response.status == "ready"
    assert response.summary.total_events == 4
    assert response.summary.failed_events == 1
    assert response.summary.provider_calls == 1
    assert [event.event_id for event in response.events] == [failed.event_id]

    manifest = json.loads((ledger.instance_dir / "manifest.json").read_text())
    assert manifest["status"] == "ended"
    assert manifest["shutdown_reason"] == "clean_shutdown"
    for path in ledger.instance_dir.iterdir():
        assert stat.S_IMODE(path.stat().st_mode) & 0o077 == 0


def test_ledger_redacts_secret_query_absolute_home_and_precise_coordinates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", "/Users/alex-private")
    ledger = FileRuntimeAuditLedger(
        root=tmp_path / "audit",
        runtime_instance_id="runtime-redaction",
    )
    ledger.start(application="scout-dashboard", runtime_profile="test")
    event = ledger.append(
        _record(
            summary=(
                "authorization=Bearer secret-token "
                "path=/Users/alex-private/workspace/trip/project.json "
                "lat=24.123456&lon=121.654321"
            ),
            detail=(
                "https://example.test/data?api_key=top-secret&project=trip_001"
            ),
            detail_code="private-secret-code",
            provider="private provider phrase",
            model="private model phrase",
        )
    )

    serialized = json.dumps(event.model_dump(mode="json"), ensure_ascii=False)
    assert "secret-token" not in serialized
    assert "top-secret" not in serialized
    assert "/Users/alex-private" not in serialized
    assert "24.123456" not in serialized
    assert "121.654321" not in serialized
    assert event.summary == "Workspace data access recorded"
    assert event.detail is None
    assert event.detail_code == "unclassified"
    assert event.provider == "other-provider"
    assert event.model == "other-model"


def test_runtime_instance_id_has_exactly_one_writer(tmp_path: Path) -> None:
    root = tmp_path / "audit"
    first = FileRuntimeAuditLedger(
        root=root,
        runtime_instance_id="runtime-single-writer",
    )
    first.start(application="scout-dashboard", runtime_profile="test")

    second = FileRuntimeAuditLedger(
        root=root,
        runtime_instance_id="runtime-single-writer",
    )
    with pytest.raises(RuntimeError, match="cannot be reused|active writer"):
        second.start(application="scout-dashboard", runtime_profile="test")


def test_workspace_artifact_reference_uses_root_scoped_keyed_digest(
    tmp_path: Path,
) -> None:
    artifact_ref = "/Users/private/workspace/trip_001/project.json"
    first = FileRuntimeAuditLedger(
        root=tmp_path / "audit-a",
        runtime_instance_id="runtime-key-a",
    )
    second = FileRuntimeAuditLedger(
        root=tmp_path / "audit-b",
        runtime_instance_id="runtime-key-b",
    )
    first.start(application="scout-dashboard", runtime_profile="test")
    second.start(application="scout-dashboard", runtime_profile="test")

    first_event = first.record_workspace_io(
        operation="write-artifact",
        workspace_id="trip_001",
        artifact_kind="route_projection",
        artifact_ref=artifact_ref,
        record_count=1,
        byte_count=64,
        module="runtime-audit-ledger",
        feature="runtime-audit",
        summary="caller prose is not persisted",
    )
    second_event = second.record_workspace_io(
        operation="write-artifact",
        workspace_id="trip_001",
        artifact_kind="route_projection",
        artifact_ref=artifact_ref,
        record_count=1,
        byte_count=64,
        module="runtime-audit-ledger",
        feature="runtime-audit",
        summary="caller prose is not persisted",
    )

    assert first_event is not None
    assert second_event is not None
    assert first_event.artifact_ref_hash != second_event.artifact_ref_hash
    assert artifact_ref not in json.dumps(first_event.model_dump(mode="json"))
    assert stat.S_IMODE((first.root / ".artifact-digest.key").stat().st_mode) == 0o600


def test_high_volume_successes_are_aggregated_but_failures_are_individual(
    tmp_path: Path,
) -> None:
    ledger = FileRuntimeAuditLedger(
        root=tmp_path / "audit",
        runtime_instance_id="runtime-http-aggregate",
        http_aggregate_flush_count=2,
    )
    ledger.start(application="scout-dashboard", runtime_profile="test")

    first = ledger.record_http_request(
        method="GET",
        route_template="/admin/pretrip/tiles/{source}/{z}/{x}/{y}.png",
        status_code=200,
        outcome="succeeded",
        duration_ms=5,
        byte_count=100,
        request_id="request-1",
        workspace_id="trip_001",
    )
    second = ledger.record_http_request(
        method="GET",
        route_template="/admin/pretrip/tiles/{source}/{z}/{x}/{y}.png",
        status_code=200,
        outcome="succeeded",
        duration_ms=7,
        byte_count=120,
        request_id="request-2",
        workspace_id="trip_001",
    )
    failed = ledger.record_http_request(
        method="GET",
        route_template="/admin/pretrip/tiles/{source}/{z}/{x}/{y}.png",
        status_code=502,
        outcome="failed",
        duration_ms=9,
        byte_count=0,
        request_id="request-3",
        workspace_id="trip_001",
        error_code="upstream-failed",
    )

    assert first is None
    assert second is not None
    assert second.request_count == 2
    assert second.duration_ms == 12
    assert second.byte_count == 220
    assert failed is not None
    assert failed.request_count == 1
    response = ledger.query(limit=100)
    assert response.summary.internal_api_calls == 3
    assert response.summary.failed_events == 1
    assert response.coverage.workspace_io.status == "partial"
    assert response.writer_health.status == "healthy"


def test_audit_writer_failure_is_reported_without_failing_workspace_operation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger = FileRuntimeAuditLedger(
        root=tmp_path / "audit",
        runtime_instance_id="runtime-writer-degraded",
    )
    ledger.start(application="scout-dashboard", runtime_profile="test")

    def fail_digest(value: str | Path | None) -> str | None:
        raise OSError("simulated audit disk failure")

    monkeypatch.setattr(ledger, "_keyed_digest", fail_digest)
    event = ledger.record_workspace_io(
        operation="write-artifact",
        workspace_id="trip_001",
        artifact_kind="route_projection",
        artifact_ref="project.json",
        record_count=1,
        byte_count=64,
        module="runtime-audit-ledger",
        feature="runtime-audit",
        summary="must not escape",
    )

    assert event is None
    response = ledger.query(limit=100)
    assert response.status == "degraded"
    assert response.writer_health.status == "degraded"
    assert response.writer_health.dropped_event_count == 1
    assert response.writer_health.last_error_code == "OSError"


def test_query_totals_and_rows_stop_at_verified_prefix_after_hash_mutation(
    tmp_path: Path,
) -> None:
    ledger = FileRuntimeAuditLedger(
        root=tmp_path / "audit",
        runtime_instance_id="runtime-mutated",
        max_events_per_file=10,
    )
    ledger.start(application="scout-dashboard", runtime_profile="test")
    ledger.append(_record(record_count=2))
    ledger.append(_record(record_count=4))
    ledger.stop(reason="clean-shutdown")

    event_path = ledger.instance_dir / "events-0001.jsonl"
    rows = [json.loads(line) for line in event_path.read_text().splitlines()]
    rows[1] = {**rows[1], "record_count": 999}
    event_path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )

    response = ledger.query(limit=100)

    assert response.status == "degraded"
    assert response.integrity.verified is False
    assert response.integrity.first_error_code == "event-hash-mismatch"
    assert response.summary.total_events == 1
    assert [event.event_type for event in response.events] == [
        "runtime.instance.started"
    ]


def test_partial_jsonl_tail_degrades_but_preserves_the_valid_prefix(
    tmp_path: Path,
) -> None:
    ledger = FileRuntimeAuditLedger(
        root=tmp_path / "audit",
        runtime_instance_id="runtime-partial-tail",
    )
    ledger.start(application="scout-dashboard", runtime_profile="test")
    ledger.stop(reason="clean-shutdown")
    event_path = ledger.instance_dir / "events-0001.jsonl"
    with event_path.open("a", encoding="utf-8") as handle:
        handle.write('{"schema_version":"scout_runtime_audit_event.v1"')

    response = ledger.query(limit=100)

    assert response.status == "degraded"
    assert response.integrity.verified is False
    assert response.integrity.first_error_code == "event-record-invalid"
    assert response.summary.total_events == 2
    assert [event.event_type for event in response.events] == [
        "runtime.instance.ended",
        "runtime.instance.started",
    ]


def test_new_runtime_marks_previous_unclosed_instance_interrupted(
    tmp_path: Path,
) -> None:
    root = tmp_path / "audit"
    first = FileRuntimeAuditLedger(
        root=root,
        runtime_instance_id="runtime-unclean",
    )
    first.start(application="scout-dashboard", runtime_profile="test")
    (first.instance_dir / ".writer.lock").write_text(
        "99999999",
        encoding="ascii",
    )

    second = FileRuntimeAuditLedger(
        root=root,
        runtime_instance_id="runtime-recovery",
    )
    start = second.start(application="scout-dashboard", runtime_profile="test")

    old_manifest = json.loads((first.instance_dir / "manifest.json").read_text())
    assert old_manifest["status"] == "interrupted"
    assert old_manifest["shutdown_reason"] == "unclean_previous_session"
    assert old_manifest["ended_at"] is None
    assert old_manifest["interruption_detected_at"]
    assert not (first.instance_dir / ".writer.lock").exists()
    degraded = second.query(event_type="audit.degraded", limit=20)
    assert degraded.summary.total_events >= 2
    assert degraded.events[0].record_count == 1
    assert start.event_type == "runtime.instance.started"


def test_new_runtime_does_not_interrupt_an_active_sibling_writer(
    tmp_path: Path,
) -> None:
    root = tmp_path / "audit"
    first = FileRuntimeAuditLedger(
        root=root,
        runtime_instance_id="runtime-active-first",
    )
    second = FileRuntimeAuditLedger(
        root=root,
        runtime_instance_id="runtime-active-second",
    )
    first.start(application="scout-dashboard", runtime_profile="test")
    second.start(application="scout-dashboard", runtime_profile="test")

    first_manifest = json.loads((first.instance_dir / "manifest.json").read_text())
    assert first_manifest["status"] == "running"
    assert second.query(event_type="audit.degraded", limit=20).events == []


def test_recovery_honors_a_durable_end_event_if_final_manifest_was_not_written(
    tmp_path: Path,
) -> None:
    root = tmp_path / "audit"
    first = FileRuntimeAuditLedger(
        root=root,
        runtime_instance_id="runtime-end-event-only",
    )
    first.start(application="scout-dashboard", runtime_profile="test")
    end_event = first.append(
        RuntimeAuditRecordInput(
            event_type="runtime.instance.ended",
            outcome="succeeded",
            category="runtime",
            subcategory="instance",
            module="scout-dashboard",
            feature="runtime-audit",
            operation="stop",
            summary="caller prose is discarded",
            detail_code="clean-shutdown",
        )
    )
    (first.instance_dir / ".writer.lock").write_text(
        "99999999",
        encoding="ascii",
    )

    second = FileRuntimeAuditLedger(
        root=root,
        runtime_instance_id="runtime-after-end-event",
    )
    second.start(application="scout-dashboard", runtime_profile="test")

    manifest = json.loads((first.instance_dir / "manifest.json").read_text())
    assert manifest["status"] == "ended"
    assert manifest["ended_at"] == end_event.recorded_at
    assert manifest["interruption_detected_at"] is None
    assert not (first.instance_dir / ".writer.lock").exists()
    assert second.query(event_type="audit.degraded", limit=20).events == []
