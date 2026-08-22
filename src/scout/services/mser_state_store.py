"""Immutable, versioned in-memory state store for MSER snapshots.

The store persists canonical candidate-only representations. It has no Phase 1
safety dependency and exposes no mutation path for runtime safety state.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from threading import RLock
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from scout.schemas.mser import EnvironmentalRepresentation


class StateVersionConflictError(RuntimeError):
    """Raised when a writer publishes against an obsolete state version."""


class StateVersionNotFoundError(LookupError):
    """Raised when a requested immutable snapshot version does not exist."""


class MSERStateSnapshot(BaseModel):
    """Frozen envelope containing a canonical serialized representation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    snapshot_id: str = Field(min_length=1)
    version: int = Field(ge=1)
    parent_version: int | None = Field(default=None, ge=1)
    created_at: datetime
    reason: str = Field(min_length=1)
    representation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    representation_json: str = Field(min_length=2, repr=False)
    candidate_only: Literal[True] = True
    runtime_safety_truth: Literal[False] = False
    phase1_safety_mutation_allowed: Literal[False] = False

    def materialize(self) -> EnvironmentalRepresentation:
        """Return a fresh model so callers cannot mutate stored state."""

        return EnvironmentalRepresentation.model_validate_json(self.representation_json)


class MSERStateStore:
    """Thread-safe append-only store with optimistic version checks."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._clock = clock or (lambda: datetime.now(UTC))
        self._snapshots: tuple[MSERStateSnapshot, ...] = ()
        self._lock = RLock()

    def publish(
        self,
        representation: EnvironmentalRepresentation,
        *,
        reason: str,
        expected_version: int | None = None,
    ) -> MSERStateSnapshot:
        """Append one immutable version without touching runtime safety state."""

        if not reason.strip():
            raise ValueError("MSER state update reason must be non-empty")
        normalized = EnvironmentalRepresentation.model_validate(
            representation.model_dump(mode="python")
        )
        self._validate_candidate_boundary(normalized)
        canonical = json.dumps(
            normalized.model_dump(mode="json"),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

        with self._lock:
            current_version = len(self._snapshots)
            if expected_version is not None and expected_version != current_version:
                raise StateVersionConflictError(
                    "MSER state version conflict: "
                    f"expected {expected_version}, current {current_version}"
                )
            version = current_version + 1
            snapshot = MSERStateSnapshot(
                snapshot_id=f"mser-state-v{version}-{digest[:12]}",
                version=version,
                parent_version=current_version or None,
                created_at=self._utc_now(),
                reason=reason.strip(),
                representation_sha256=digest,
                representation_json=canonical,
            )
            self._snapshots = (*self._snapshots, snapshot)
            return snapshot

    def current(self) -> MSERStateSnapshot | None:
        with self._lock:
            return self._snapshots[-1] if self._snapshots else None

    def get(self, version: int) -> MSERStateSnapshot:
        with self._lock:
            if version < 1 or version > len(self._snapshots):
                raise StateVersionNotFoundError(
                    f"MSER state version does not exist: {version}"
                )
            return self._snapshots[version - 1]

    def history(self) -> tuple[MSERStateSnapshot, ...]:
        with self._lock:
            return self._snapshots

    @property
    def version(self) -> int:
        with self._lock:
            return len(self._snapshots)

    def _utc_now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @staticmethod
    def _validate_candidate_boundary(
        representation: EnvironmentalRepresentation,
    ) -> None:
        if not representation.candidate_only or representation.runtime_safety_truth:
            raise ValueError("MSER state must remain candidate-only")
        for signal in representation.all_signals():
            if not signal.candidate_only or signal.runtime_safety_truth:
                raise ValueError(
                    f"MSER signal crossed runtime safety boundary: {signal.signal_id}"
                )


__all__ = [
    "MSERStateSnapshot",
    "MSERStateStore",
    "StateVersionConflictError",
    "StateVersionNotFoundError",
]
