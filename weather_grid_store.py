from __future__ import annotations

import gzip
import hashlib
import json
import os
import tempfile
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from threading import RLock
from typing import Any

import fcntl

from cwa_precipitation_grid import CwaPrecipitationGrid
from rainfall_grid_freshness import evaluate_precipitation_freshness


MAX_COMPRESSED_GRID_BYTES = 8 * 1024 * 1024
MAX_DECOMPRESSED_GRID_BYTES = 32 * 1024 * 1024
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
MANIFEST_PROVENANCE_KEYS = frozenset(
    {
        "projectId",
        "routeRef",
        "routeSha256",
        "routeBasis",
        "routeSourceRef",
        "routeSourceSha256",
        "sourceFrameIds",
        "pairId",
    }
)


def rainfall_product_freshness(
    product: dict[str, Any],
    *,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    return evaluate_precipitation_freshness(
        grid_kind=str(product.get("gridKind") or ""),
        source_timestamp=product.get("sourceTimestamp"),
        valid_until=product.get("validUntil"),
        evaluated_at=evaluated_at,
    )


def rainfall_products_status(products: list[dict[str, Any]]) -> str:
    required_kinds = {"qpe_past_1h", "qpf_next_1h"}
    available_kinds = {
        str(product.get("gridKind") or "")
        for product in products
        if product.get("gridKind")
    }
    if not required_kinds.issubset(available_kinds):
        return "missing_source"
    statuses = {
        str((product.get("freshness") or {}).get("status") or "unknown")
        for product in products
    }
    if not products:
        return "missing_source"
    if statuses == {"current"}:
        return "ready"
    if statuses == {"stale_data"}:
        return "stale_data"
    if "stale_data" in statuses:
        return "partially_stale"
    return "unknown_freshness"


@lru_cache(maxsize=128)
def _thread_lock_for_root(root: str) -> RLock:
    del root
    return RLock()


def _validated_manifest_provenance(
    value: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if value is None:
        return {}
    unknown = set(value) - MANIFEST_PROVENANCE_KEYS
    if unknown:
        raise ValueError(
            f"unsupported rainfall manifest provenance keys: {sorted(unknown)}"
        )
    normalized: dict[str, Any] = {}
    for key in MANIFEST_PROVENANCE_KEYS - {"sourceFrameIds"}:
        if key not in value:
            continue
        item = value[key]
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"rainfall manifest provenance {key} is invalid")
        normalized[key] = item.strip()
    source_frame_ids = value.get("sourceFrameIds")
    if source_frame_ids is not None:
        if not isinstance(source_frame_ids, Mapping):
            raise ValueError("rainfall sourceFrameIds must be a mapping")
        normalized_ids = {
            str(kind): str(frame_id)
            for kind, frame_id in source_frame_ids.items()
            if str(kind) and str(frame_id)
        }
        if len(normalized_ids) != len(source_frame_ids):
            raise ValueError("rainfall sourceFrameIds contains an invalid entry")
        normalized["sourceFrameIds"] = dict(sorted(normalized_ids.items()))
    route_sha = normalized.get("routeSha256")
    if route_sha is not None and (
        len(route_sha) != 64
        or any(char not in "0123456789abcdefABCDEF" for char in route_sha)
    ):
        raise ValueError("rainfall routeSha256 must be a SHA-256 hex digest")
    route_source_sha = normalized.get("routeSourceSha256")
    if route_source_sha is not None and route_source_sha != route_sha:
        raise ValueError("rainfall route source SHA aliases do not match")
    if "pairId" in normalized:
        required = {
            "projectId",
            "routeRef",
            "routeSha256",
            "routeBasis",
            "sourceFrameIds",
        }
        missing = required - set(normalized)
        if missing:
            raise ValueError(
                f"rainfall pair provenance is incomplete: {sorted(missing)}"
            )
    return normalized


class WeatherGridStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def put(self, grid: CwaPrecipitationGrid) -> Path:
        frame = _frame_payload(grid)
        canonical = _canonical_json(frame)
        digest = hashlib.sha256(
            _canonical_json(_frame_identity_payload(frame))
        ).hexdigest()
        timestamp = grid.source_timestamp.strftime("%Y%m%dT%H%M%S%z")
        destination = self._safe_path(
            Path("grids") / grid.dataset_id / f"{timestamp}-{digest[:16]}.json.gz"
        )
        if destination.exists():
            return destination
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(prefix=".grid-", dir=destination.parent)
        try:
            with os.fdopen(fd, "wb") as raw_handle:
                with gzip.GzipFile(fileobj=raw_handle, mode="wb", mtime=0) as handle:
                    handle.write(canonical)
                raw_handle.flush()
                os.fsync(raw_handle.fileno())
            Path(temporary_name).replace(destination)
        except Exception:
            Path(temporary_name).unlink(missing_ok=True)
            raise
        return destination

    def stage_frames(
        self,
        grids: Sequence[CwaPrecipitationGrid],
    ) -> list[dict[str, Any]]:
        if not grids:
            raise ValueError("at least one weather grid is required")
        frames: list[dict[str, Any]] = []
        for grid in grids:
            path = self.put(grid)
            stored_grid = load_weather_grid_snapshot(path)
            frame = _compact_frame(
                stored_grid,
                path.relative_to(self.root).as_posix(),
            )
            frames.append(frame)
        return frames

    @contextmanager
    def staged_manifest_update(
        self,
        frames: Sequence[Mapping[str, Any]],
        *,
        provenance: Mapping[str, Any] | None = None,
        on_publish_error: Callable[[], None] | None = None,
    ) -> Iterator[dict[str, Any]]:
        staged_frames = [dict(frame) for frame in frames]
        if not staged_frames:
            raise ValueError("at least one weather grid frame is required")
        with self._manifest_update_lock():
            manifest = self._build_manifest(
                staged_frames,
                provenance=provenance,
            )
            try:
                yield manifest
                self._atomic_json(
                    self.root / "rainfall_grid_manifest.json",
                    manifest,
                )
            except Exception:
                if on_publish_error is not None:
                    on_publish_error()
                raise

    def update_manifest(
        self,
        grids: Sequence[CwaPrecipitationGrid],
        *,
        provenance: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        frames = self.stage_frames(grids)
        with self.staged_manifest_update(frames, provenance=provenance) as manifest:
            published = manifest
        return published

    def _build_manifest(
        self,
        frames: list[dict[str, Any]],
        *,
        provenance: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        latest: dict[str, dict[str, Any]] = {}
        for frame in frames:
            kind = str(frame.get("gridKind") or "")
            if not kind:
                raise ValueError("weather grid frame kind is missing")
            existing = latest.get(kind)
            if existing is None or _frame_recency(frame) > _frame_recency(existing):
                latest[kind] = frame
        previous = self._read_manifest()
        by_id = {
            str(item.get("frameId")): item
            for item in previous.get("frames", [])
            if isinstance(item, dict) and item.get("frameId")
        }
        by_id.update({frame["frameId"]: frame for frame in frames})
        all_frames = sorted(
            by_id.values(),
            key=lambda item: (item["sourceTimestamp"], item["datasetId"]),
        )
        for frame in all_frames:
            current = latest.get(frame["gridKind"])
            if current is None or _frame_recency(frame) > _frame_recency(current):
                latest[frame["gridKind"]] = frame
        manifest_provenance = _validated_manifest_provenance(provenance)
        manifest: dict[str, Any] = {
            "schemaVersion": "cwa_rainfall_grid_manifest.v1",
            "artifactKind": "cwa_rainfall_grid_manifest",
            "frames": all_frames,
            "latestByKind": latest,
            "cachePolicy": {
                "cacheable": False,
                "ttlSeconds": 0,
                "mustRefetchOnPrepare": True,
                "reusePreviousAsCurrentTruth": False,
                "persistedRole": "immutable_evidence_snapshot",
            },
            "boundary": {
                "candidateOnly": True,
                "runtimeSafetyTruth": False,
                "raspberryPiGridProcessing": False,
                "mobileGridProcessing": False,
            },
            **manifest_provenance,
        }
        if manifest_provenance.get("pairId"):
            manifest["activePair"] = {
                key: manifest_provenance[key]
                for key in (
                    "pairId",
                    "projectId",
                    "routeRef",
                    "routeSha256",
                    "routeBasis",
                    "sourceFrameIds",
                )
                if key in manifest_provenance
            }
        return manifest

    def public_manifest(
        self,
        *,
        evaluated_at: datetime | None = None,
    ) -> dict[str, Any]:
        manifest = self._read_manifest()
        products = []
        for kind, frame in sorted((manifest.get("latestByKind") or {}).items()):
            if not isinstance(frame, dict):
                continue
            product = {
                key: frame.get(key)
                for key in (
                    "frameId",
                    "datasetId",
                    "gridKind",
                    "sourceTimestamp",
                    "fetchedAt",
                    "validFrom",
                    "validUntil",
                    "dataDelayMinutes",
                    "expectedDelayMinutes",
                    "unit",
                    "boundsWgs84",
                    "width",
                    "height",
                )
            }
            product["freshness"] = rainfall_product_freshness(
                product,
                evaluated_at=evaluated_at,
            )
            products.append(product)
        public = {
            "schemaVersion": manifest.get("schemaVersion"),
            "artifactKind": manifest.get("artifactKind"),
            "status": rainfall_products_status(products),
            "products": products,
            "cachePolicy": {
                "cacheable": False,
                "ttlSeconds": 0,
                "mustRefetchOnPrepare": True,
                "reusePreviousAsCurrentTruth": False,
            },
            "boundary": {
                "candidateOnly": True,
                "runtimeSafetyTruth": False,
                "raspberryPiGridProcessing": False,
                "mobileGridProcessing": False,
            },
        }
        for key in (
            "projectId",
            "routeRef",
            "routeSha256",
            "routeBasis",
            "routeSourceRef",
            "routeSourceSha256",
            "sourceFrameIds",
            "pairId",
            "activePair",
        ):
            if key in manifest:
                public[key] = manifest[key]
        return public

    def _read_manifest(self) -> dict[str, Any]:
        path = self.root / "rainfall_grid_manifest.json"
        if not path.exists():
            return {}
        if path.stat().st_size > MAX_MANIFEST_BYTES:
            raise ValueError("weather grid manifest exceeds size limit")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if (
            not isinstance(payload, dict)
            or payload.get("artifactKind") != "cwa_rainfall_grid_manifest"
        ):
            raise ValueError("invalid weather grid manifest contract")
        _validate_manifest_active_pair(payload)
        return payload

    def _safe_path(self, relative: Path) -> Path:
        destination = (self.root / relative).resolve()
        if self.root not in destination.parents:
            raise ValueError("weather grid path escapes store root")
        return destination

    @contextmanager
    def _manifest_update_lock(self) -> Iterator[None]:
        self.root.mkdir(parents=True, exist_ok=True)
        thread_lock = _thread_lock_for_root(str(self.root))
        with thread_lock:
            lock_path = self.root / ".rainfall-grid-manifest.lock"
            with lock_path.open("a+b") as lock_file:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _atomic_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = _canonical_json(payload) + b"\n"
        fd, temporary_name = tempfile.mkstemp(prefix=".manifest-", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            Path(temporary_name).replace(path)
        except Exception:
            Path(temporary_name).unlink(missing_ok=True)
            raise


def _frame_payload(grid: CwaPrecipitationGrid) -> dict[str, Any]:
    payload = grid.model_dump(mode="json", by_alias=True)
    values = payload.pop("values")
    boundary = payload.pop("boundary")
    return {
        "schemaVersion": payload.pop("schema_version"),
        "artifactKind": payload.pop("artifact_kind"),
        "metadata": payload,
        "grid": {"values": values},
        "cachePolicy": {
            "cacheable": False,
            "ttlSeconds": 0,
            "mustRefetchOnPrepare": True,
            "reusePreviousAsCurrentTruth": False,
        },
        "boundary": boundary,
    }


def _validate_manifest_active_pair(manifest: Mapping[str, Any]) -> None:
    if manifest.get("pairId") is None and manifest.get("sourceFrameIds") is None:
        return
    provenance = _validated_manifest_provenance(
        {
            key: manifest[key]
            for key in MANIFEST_PROVENANCE_KEYS
            if key in manifest
        }
    )
    latest = manifest.get("latestByKind")
    if not isinstance(latest, Mapping):
        raise ValueError("rainfall manifest active source frames are missing")
    active_source_frames = {
        str(kind): str(frame.get("frameId") or "")
        for kind, frame in latest.items()
        if isinstance(frame, Mapping)
    }
    if provenance.get("sourceFrameIds") != active_source_frames:
        raise ValueError("rainfall manifest active source frames mismatch")
    identity = {
        key: provenance[key]
        for key in (
            "projectId",
            "routeRef",
            "routeSha256",
            "routeBasis",
            "sourceFrameIds",
        )
    }
    expected_pair_id = "cwa.rainfall.pair." + hashlib.sha256(
        _canonical_json(identity)
    ).hexdigest()
    if provenance.get("pairId") != expected_pair_id:
        raise ValueError("rainfall manifest pairId does not match active provenance")
    active_pair = manifest.get("activePair")
    if active_pair is not None:
        if not isinstance(active_pair, Mapping):
            raise ValueError("rainfall manifest activePair is invalid")
        expected_active_pair = {
            key: provenance[key]
            for key in (
                "pairId",
                "projectId",
                "routeRef",
                "routeSha256",
                "routeBasis",
                "sourceFrameIds",
            )
        }
        if dict(active_pair) != expected_active_pair:
            raise ValueError("rainfall manifest activePair mismatch")


def _frame_identity_payload(frame: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(frame["metadata"])
    metadata.pop("fetched_at", None)
    metadata.pop("data_delay_minutes", None)
    return {
        "schemaVersion": frame["schemaVersion"],
        "artifactKind": frame["artifactKind"],
        "metadata": metadata,
        "grid": frame["grid"],
        "boundary": frame["boundary"],
    }


def _compact_frame(grid: CwaPrecipitationGrid, data_ref: str) -> dict[str, Any]:
    digest = Path(data_ref).name.rsplit("-", 1)[-1].removesuffix(".json.gz")
    return {
        "frameId": f"{grid.dataset_id}.{grid.source_timestamp.isoformat()}.{digest}",
        "datasetId": grid.dataset_id,
        "gridKind": grid.grid_kind,
        "sourceTimestamp": grid.source_timestamp.isoformat(),
        "fetchedAt": grid.fetched_at.isoformat(),
        "validFrom": grid.valid_from.isoformat(),
        "validUntil": grid.valid_until.isoformat(),
        "dataDelayMinutes": grid.data_delay_minutes,
        "expectedDelayMinutes": grid.expected_delay_minutes,
        "unit": grid.unit,
        "boundsWgs84": list(grid.bounds_wgs84),
        "width": grid.width,
        "height": grid.height,
        "dataRef": data_ref,
    }


def _canonical_json(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _frame_recency(frame: dict[str, Any]) -> tuple[str, str]:
    return str(frame.get("sourceTimestamp", "")), str(frame.get("fetchedAt", ""))


def load_weather_grid_snapshot(path: Path) -> CwaPrecipitationGrid:
    resolved = path.resolve()
    try:
        if resolved.stat().st_size > MAX_COMPRESSED_GRID_BYTES:
            raise ValueError("compressed weather grid exceeds size limit")
        with gzip.open(resolved, "rb") as handle:
            raw = handle.read(MAX_DECOMPRESSED_GRID_BYTES + 1)
    except OSError as exc:
        raise ValueError("invalid compressed weather grid") from exc
    if len(raw) > MAX_DECOMPRESSED_GRID_BYTES:
        raise ValueError("decompressed weather grid exceeds size limit")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("invalid weather grid JSON") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("artifactKind") != "cwa_precipitation_grid"
    ):
        raise ValueError("invalid weather grid contract")
    metadata = payload.get("metadata")
    grid = payload.get("grid")
    boundary = payload.get("boundary")
    if (
        not isinstance(metadata, dict)
        or not isinstance(grid, dict)
        or not isinstance(boundary, dict)
    ):
        raise ValueError("incomplete weather grid contract")
    values = grid.get("values")
    if not isinstance(values, list):
        raise ValueError("weather grid values missing")
    try:
        normalized = CwaPrecipitationGrid.model_validate(
            {
                "schema_version": payload.get("schemaVersion"),
                "artifact_kind": payload.get("artifactKind"),
                **metadata,
                "values": values,
                "boundary": boundary,
            }
        )
    except Exception as exc:
        raise ValueError("invalid normalized weather grid") from exc
    expected_digest = hashlib.sha256(
        _canonical_json(_frame_identity_payload(payload))
    ).hexdigest()[:16]
    filename_digest = resolved.name.removesuffix(".json.gz").rsplit("-", 1)[-1]
    if filename_digest != expected_digest:
        raise ValueError("weather grid content hash does not match filename")
    return normalized
