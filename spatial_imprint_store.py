from __future__ import annotations

import json
import os
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from spatial_imprint_models import (
    SpatialImprint,
    SpatialImprintBoundary,
    SpatialImprintLifecycle,
    SpatialImprintLifecycleScope,
    SpatialImprintLifecycleState,
    SpatialImprintSet,
    parse_spatial_datetime,
    spatial_utc_now,
)


SpatialImprintStoreAction = Literal[
    "planted",
    "expired",
    "deleted_tombstone",
]


class SpatialImprintStoreModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SpatialImprintStoreBoundary(SpatialImprintStoreModel):
    advisory_cue_store: Literal[True] = True
    operator_or_user_triggered: Literal[True] = True
    runtime_safety_truth: Literal[False] = False
    phase1_safety_mutation_allowed: Literal[False] = False
    live_safety_api_calls_allowed: Literal[False] = False
    remote_outbound_send_allowed: Literal[False] = False
    hardware_control_allowed: Literal[False] = False


class SpatialImprintStoreAuditRecord(SpatialImprintStoreModel):
    audit_id: str = Field(min_length=1)
    action: SpatialImprintStoreAction
    imprint_id: str = Field(min_length=1)
    actor_ref: str = Field(min_length=1)
    acted_at: str
    reason: str | None = None
    previous_lifecycle: dict[str, Any] | None = None
    new_lifecycle: dict[str, Any] | None = None
    boundary: SpatialImprintStoreBoundary = Field(default_factory=SpatialImprintStoreBoundary)

    @field_validator("acted_at")
    @classmethod
    def validate_acted_at(cls, value: str) -> str:
        parse_spatial_datetime(value)
        return value


class SpatialImprintStoreCounts(SpatialImprintStoreModel):
    imprint_count: int = Field(ge=0)
    active_count: int = Field(ge=0)
    ttl_scoped_count: int = Field(ge=0)
    trip_scoped_count: int = Field(ge=0)
    admin_persistent_count: int = Field(ge=0)
    deleted_tombstone_count: int = Field(ge=0)
    audit_record_count: int = Field(ge=0)
    runtime_truth_count: Literal[0] = 0
    phase1_runtime_mutation_count: Literal[0] = 0
    safety_api_call_count: Literal[0] = 0
    remote_outbound_send_count: Literal[0] = 0
    hardware_control_count: Literal[0] = 0


class SpatialImprintStoreDocument(SpatialImprintStoreModel):
    artifact_kind: Literal["spatial_imprint_store"] = "spatial_imprint_store"
    schema_version: str = "0.1.0"
    trip_id: str = Field(min_length=1)
    imprints: list[SpatialImprint] = Field(default_factory=list)
    audit_log: list[SpatialImprintStoreAuditRecord] = Field(default_factory=list)
    counts: SpatialImprintStoreCounts
    boundary: SpatialImprintStoreBoundary = Field(default_factory=SpatialImprintStoreBoundary)

    @model_validator(mode="after")
    def enforce_store_boundary(self) -> "SpatialImprintStoreDocument":
        ids = [imprint.imprint_id for imprint in self.imprints]
        if len(ids) != len(set(ids)):
            raise ValueError("spatial imprint store contains duplicate imprint_id")
        if any(imprint.boundary.runtime_safety_truth for imprint in self.imprints):
            raise ValueError("spatial imprint store must not contain runtime safety truth")
        if self.counts.runtime_truth_count != 0:
            raise ValueError("spatial imprint store runtime truth count must stay zero")
        _assert_no_forbidden_fragments(self.model_dump(mode="json"))
        return self

    def to_json(self) -> str:
        return _json_text(self.model_dump(mode="json"))


def empty_spatial_imprint_store(trip_id: str) -> SpatialImprintStoreDocument:
    return _rebuild_store(
        trip_id=trip_id,
        imprints=[],
        audit_log=[],
    )


def load_spatial_imprint_store(
    path: Path | str,
    *,
    trip_id: str | None = None,
) -> SpatialImprintStoreDocument:
    store_path = Path(path)
    if not store_path.exists():
        if trip_id is None:
            raise FileNotFoundError(f"missing spatial imprint store: {store_path}")
        return empty_spatial_imprint_store(trip_id)
    return SpatialImprintStoreDocument.model_validate_json(
        store_path.read_text(encoding="utf-8")
    )


def write_spatial_imprint_store(
    path: Path | str,
    store: SpatialImprintStoreDocument,
) -> None:
    _replace_json(Path(path), store.to_json())


def plant_spatial_imprint(
    path: Path | str,
    imprint: SpatialImprint | dict[str, Any],
    *,
    trip_id: str,
    authorized_by: str,
    planted_at: str | None = None,
    reason: str | None = None,
    allow_admin_persistent: bool = False,
) -> SpatialImprintStoreDocument:
    if not authorized_by:
        raise ValueError("planting a spatial imprint requires authorized_by")
    candidate = SpatialImprint.model_validate(imprint)
    if (
        candidate.lifecycle.scope == SpatialImprintLifecycleScope.ADMIN_PERSISTENT
        and not allow_admin_persistent
    ):
        raise ValueError("admin_persistent spatial imprints require explicit admin allowance")
    store = load_spatial_imprint_store(path, trip_id=trip_id)
    if store.trip_id != trip_id:
        raise ValueError("spatial imprint store trip_id does not match request")
    if any(existing.imprint_id == candidate.imprint_id for existing in store.imprints):
        raise ValueError(f"spatial imprint already exists: {candidate.imprint_id}")
    acted_at = planted_at or spatial_utc_now()
    audit = _audit_record(
        action="planted",
        imprint_id=candidate.imprint_id,
        actor_ref=authorized_by,
        acted_at=acted_at,
        reason=reason,
        new_lifecycle=candidate.lifecycle,
    )
    updated = _rebuild_store(
        trip_id=store.trip_id,
        imprints=[*store.imprints, candidate],
        audit_log=[*store.audit_log, audit],
    )
    write_spatial_imprint_store(path, updated)
    return updated


def expire_spatial_imprint(
    path: Path | str,
    *,
    imprint_id: str,
    authorized_by: str,
    expired_at: str | None = None,
    reason: str | None = None,
) -> SpatialImprintStoreDocument:
    if not authorized_by:
        raise ValueError("expiring a spatial imprint requires authorized_by")
    acted_at = expired_at or spatial_utc_now()
    store = load_spatial_imprint_store(path)
    imprints = list(store.imprints)
    index, current = _find_imprint(imprints, imprint_id)
    previous = current.lifecycle
    updated_lifecycle = current.lifecycle.model_copy(
        update={"state": SpatialImprintLifecycleState.ACTIVE, "expires_at": acted_at}
    )
    imprints[index] = _with_lifecycle(current, updated_lifecycle)
    audit = _audit_record(
        action="expired",
        imprint_id=imprint_id,
        actor_ref=authorized_by,
        acted_at=acted_at,
        reason=reason,
        previous_lifecycle=previous,
        new_lifecycle=updated_lifecycle,
    )
    updated = _rebuild_store(
        trip_id=store.trip_id,
        imprints=imprints,
        audit_log=[*store.audit_log, audit],
    )
    write_spatial_imprint_store(path, updated)
    return updated


def delete_spatial_imprint_tombstone(
    path: Path | str,
    *,
    imprint_id: str,
    authorized_by: str,
    deleted_at: str | None = None,
    reason: str | None = None,
) -> SpatialImprintStoreDocument:
    if not authorized_by:
        raise ValueError("deleting a spatial imprint requires authorized_by")
    acted_at = deleted_at or spatial_utc_now()
    store = load_spatial_imprint_store(path)
    imprints = list(store.imprints)
    index, current = _find_imprint(imprints, imprint_id)
    previous = current.lifecycle
    updated_lifecycle = current.lifecycle.model_copy(
        update={"state": SpatialImprintLifecycleState.DELETED_TOMBSTONE}
    )
    imprints[index] = _with_lifecycle(current, updated_lifecycle)
    audit = _audit_record(
        action="deleted_tombstone",
        imprint_id=imprint_id,
        actor_ref=authorized_by,
        acted_at=acted_at,
        reason=reason,
        previous_lifecycle=previous,
        new_lifecycle=updated_lifecycle,
    )
    updated = _rebuild_store(
        trip_id=store.trip_id,
        imprints=imprints,
        audit_log=[*store.audit_log, audit],
    )
    write_spatial_imprint_store(path, updated)
    return updated


def spatial_imprint_set_from_store(
    store: SpatialImprintStoreDocument,
    *,
    include_inactive: bool = False,
) -> SpatialImprintSet:
    imprints = [
        imprint
        for imprint in store.imprints
        if include_inactive or imprint.lifecycle.state == SpatialImprintLifecycleState.ACTIVE
    ]
    return SpatialImprintSet(trip_id=store.trip_id, imprints=imprints)


def _with_lifecycle(
    imprint: SpatialImprint,
    lifecycle: SpatialImprintLifecycle,
) -> SpatialImprint:
    return SpatialImprint.model_validate(
        {
            **imprint.model_dump(mode="json"),
            "lifecycle": lifecycle.model_dump(mode="json"),
            "boundary": SpatialImprintBoundary().model_dump(mode="json"),
        }
    )


def _find_imprint(
    imprints: list[SpatialImprint],
    imprint_id: str,
) -> tuple[int, SpatialImprint]:
    for index, imprint in enumerate(imprints):
        if imprint.imprint_id == imprint_id:
            return index, imprint
    raise ValueError(f"unknown spatial imprint: {imprint_id}")


def _audit_record(
    *,
    action: SpatialImprintStoreAction,
    imprint_id: str,
    actor_ref: str,
    acted_at: str,
    reason: str | None,
    previous_lifecycle: SpatialImprintLifecycle | None = None,
    new_lifecycle: SpatialImprintLifecycle | None = None,
) -> SpatialImprintStoreAuditRecord:
    return SpatialImprintStoreAuditRecord(
        audit_id=f"spatial_imprint_audit.{_safe_token(imprint_id)}.{action}.{len(actor_ref)}",
        action=action,
        imprint_id=imprint_id,
        actor_ref=actor_ref,
        acted_at=acted_at,
        reason=reason,
        previous_lifecycle=(
            previous_lifecycle.model_dump(mode="json") if previous_lifecycle else None
        ),
        new_lifecycle=new_lifecycle.model_dump(mode="json") if new_lifecycle else None,
    )


def _rebuild_store(
    *,
    trip_id: str,
    imprints: list[SpatialImprint],
    audit_log: list[SpatialImprintStoreAuditRecord],
) -> SpatialImprintStoreDocument:
    lifecycle_counts = Counter(imprint.lifecycle.scope for imprint in imprints)
    active_count = sum(
        1 for imprint in imprints if imprint.lifecycle.state == SpatialImprintLifecycleState.ACTIVE
    )
    deleted_count = sum(
        1
        for imprint in imprints
        if imprint.lifecycle.state == SpatialImprintLifecycleState.DELETED_TOMBSTONE
    )
    return SpatialImprintStoreDocument(
        trip_id=trip_id,
        imprints=imprints,
        audit_log=audit_log,
        counts=SpatialImprintStoreCounts(
            imprint_count=len(imprints),
            active_count=active_count,
            ttl_scoped_count=lifecycle_counts[SpatialImprintLifecycleScope.TTL_SCOPED],
            trip_scoped_count=lifecycle_counts[SpatialImprintLifecycleScope.TRIP_SCOPED],
            admin_persistent_count=lifecycle_counts[
                SpatialImprintLifecycleScope.ADMIN_PERSISTENT
            ],
            deleted_tombstone_count=deleted_count,
            audit_record_count=len(audit_log),
        ),
    )


def _replace_json(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as tmp_file:
            tmp_name = tmp_file.name
            tmp_file.write(payload)
            tmp_file.flush()
            os.fsync(tmp_file.fileno())
        os.replace(tmp_name, path)
    finally:
        if tmp_name and Path(tmp_name).exists():
            Path(tmp_name).unlink()


def _json_text(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _safe_token(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._:-" else "_" for ch in value)


def _assert_no_forbidden_fragments(payload: Any) -> None:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    forbidden = (
        "/safety/",
        "Phase1IncidentBridge",
        "ObservedFact",
        "Final MissionGraph",
        "MissionGraph(",
        "raw_gpx",
        "raw_payload",
    )
    for fragment in forbidden:
        if fragment in text:
            raise ValueError(f"forbidden spatial imprint store fragment: {fragment}")
