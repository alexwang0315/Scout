from __future__ import annotations

import json

import pytest

from spatial_imprint_cli import run_spatial_imprint_cli
from spatial_imprint_models import SpatialImprintSet
from spatial_imprint_store import (
    delete_spatial_imprint_tombstone,
    expire_spatial_imprint,
    load_spatial_imprint_store,
    plant_spatial_imprint,
    spatial_imprint_set_from_store,
)
from spatial_imprint_trigger import evaluate_spatial_imprints
from tests.test_spatial_imprint_trigger import _context, _imprint


def test_spatial_imprint_store_plants_and_exports_active_trigger_set(tmp_path) -> None:
    store_path = tmp_path / "runtime_spatial_imprints.json"
    imprint = _imprint(
        imprint_id="spatial_imprint.runtime.rest.001",
        planting_source="operator_runtime",
        lifecycle={"state": "active", "scope": "ttl_scoped", "ttl_seconds": 1800},
    )

    store = plant_spatial_imprint(
        store_path,
        imprint,
        trip_id="chilai_nanhua_day1",
        authorized_by="leader.alex",
        planted_at="2026-05-26T12:00:00+08:00",
        reason="Team rest cue.",
    )
    imprint_set = spatial_imprint_set_from_store(store)

    assert store.counts.imprint_count == 1
    assert store.counts.ttl_scoped_count == 1
    assert store.counts.audit_record_count == 1
    assert store.boundary.phase1_safety_mutation_allowed is False
    assert store.audit_log[0].action == "planted"
    assert imprint_set.trip_id == "chilai_nanhua_day1"
    assert imprint_set.imprints[0].imprint_id == "spatial_imprint.runtime.rest.001"

    report = evaluate_spatial_imprints(imprint_set, _context())
    assert report.counts["triggered"] == 1
    assert report.boundary.live_safety_api_calls_allowed is False


def test_spatial_imprint_store_rejects_duplicate_and_unapproved_persistent(tmp_path) -> None:
    store_path = tmp_path / "runtime_spatial_imprints.json"
    imprint = _imprint(
        imprint_id="spatial_imprint.runtime.unique.001",
        planting_source="operator_runtime",
    )
    plant_spatial_imprint(
        store_path,
        imprint,
        trip_id="chilai_nanhua_day1",
        authorized_by="leader.alex",
    )

    with pytest.raises(ValueError, match="already exists"):
        plant_spatial_imprint(
            store_path,
            imprint,
            trip_id="chilai_nanhua_day1",
            authorized_by="leader.alex",
        )

    persistent = _imprint(
        imprint_id="spatial_imprint.runtime.persistent.001",
        planting_source="operator_runtime",
        lifecycle={"state": "active", "scope": "admin_persistent"},
    )
    with pytest.raises(ValueError, match="admin_persistent"):
        plant_spatial_imprint(
            store_path,
            persistent,
            trip_id="chilai_nanhua_day1",
            authorized_by="leader.alex",
        )


def test_spatial_imprint_store_expire_and_delete_keep_tombstone_audit(tmp_path) -> None:
    store_path = tmp_path / "runtime_spatial_imprints.json"
    imprint = _imprint(
        imprint_id="spatial_imprint.runtime.temp.001",
        planting_source="operator_runtime",
    )
    plant_spatial_imprint(
        store_path,
        imprint,
        trip_id="chilai_nanhua_day1",
        authorized_by="leader.alex",
    )

    expired = expire_spatial_imprint(
        store_path,
        imprint_id="spatial_imprint.runtime.temp.001",
        authorized_by="leader.alex",
        expired_at="2026-05-26T09:00:00+08:00",
        reason="No longer relevant.",
    )
    expired_event = evaluate_spatial_imprints(
        spatial_imprint_set_from_store(expired),
        _context(),
    ).events[0]
    assert expired_event.status == "expired"
    assert expired.audit_log[-1].action == "expired"

    deleted = delete_spatial_imprint_tombstone(
        store_path,
        imprint_id="spatial_imprint.runtime.temp.001",
        authorized_by="leader.alex",
        deleted_at="2026-05-26T09:05:00+08:00",
        reason="Admin deleted.",
    )

    assert deleted.counts.deleted_tombstone_count == 1
    assert deleted.counts.audit_record_count == 3
    assert deleted.audit_log[-1].action == "deleted_tombstone"
    assert spatial_imprint_set_from_store(deleted).imprints == []
    assert spatial_imprint_set_from_store(deleted, include_inactive=True).imprints[0].lifecycle.state == "deleted_tombstone"


def test_spatial_imprint_store_cli_plant_list_expire_delete(tmp_path) -> None:
    store_path = tmp_path / "runtime_spatial_imprints.json"
    imprint_path = tmp_path / "imprint.json"
    imprint_path.write_text(
        _imprint(
            imprint_id="spatial_imprint.runtime.cli.001",
            planting_source="operator_runtime",
        ).model_dump_json(),
        encoding="utf-8",
    )

    plant_exit, plant_payload = run_spatial_imprint_cli(
        [
            "plant",
            "--store",
            str(store_path),
            "--input",
            str(imprint_path),
            "--trip-id",
            "chilai_nanhua_day1",
            "--authorized-by",
            "leader.alex",
            "--planted-at",
            "2026-05-26T12:00:00+08:00",
        ]
    )
    assert plant_exit == 0
    assert plant_payload["action"] == "planted"
    assert plant_payload["boundary"]["phase1_safety_mutation_allowed"] is False

    list_exit, list_payload = run_spatial_imprint_cli(
        ["store-list", "--store", str(store_path)]
    )
    assert list_exit == 0
    assert list_payload["active_imprint_set"]["artifact_kind"] == "spatial_imprint_set"
    assert list_payload["active_imprint_set"]["imprints"][0]["imprint_id"] == "spatial_imprint.runtime.cli.001"

    expire_exit, expire_payload = run_spatial_imprint_cli(
        [
            "expire",
            "--store",
            str(store_path),
            "--imprint-id",
            "spatial_imprint.runtime.cli.001",
            "--authorized-by",
            "leader.alex",
            "--expired-at",
            "2026-05-26T09:00:00+08:00",
        ]
    )
    assert expire_exit == 0
    assert expire_payload["action"] == "expired"

    delete_exit, delete_payload = run_spatial_imprint_cli(
        [
            "delete",
            "--store",
            str(store_path),
            "--imprint-id",
            "spatial_imprint.runtime.cli.001",
            "--authorized-by",
            "leader.alex",
            "--deleted-at",
            "2026-05-26T09:05:00+08:00",
        ]
    )
    assert delete_exit == 0
    assert delete_payload["action"] == "deleted_tombstone"
    assert load_spatial_imprint_store(store_path).counts.deleted_tombstone_count == 1


def test_spatial_imprint_store_document_rejects_runtime_truth_fragment(tmp_path) -> None:
    store_path = tmp_path / "bad_store.json"
    payload = {
        "artifact_kind": "spatial_imprint_store",
        "trip_id": "chilai_nanhua_day1",
        "imprints": [],
        "audit_log": [],
        "counts": {
            "imprint_count": 0,
            "active_count": 0,
            "ttl_scoped_count": 0,
            "trip_scoped_count": 0,
            "admin_persistent_count": 0,
            "deleted_tombstone_count": 0,
            "audit_record_count": 0,
            "runtime_truth_count": 1,
        },
    }
    store_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="runtime_truth_count|runtime truth count"):
        load_spatial_imprint_store(store_path)


def test_spatial_imprint_store_exports_valid_set_model(tmp_path) -> None:
    store = plant_spatial_imprint(
        tmp_path / "store.json",
        _imprint(planting_source="operator_runtime"),
        trip_id="chilai_nanhua_day1",
        authorized_by="leader.alex",
    )

    SpatialImprintSet.model_validate(
        spatial_imprint_set_from_store(store).model_dump(mode="json")
    )
