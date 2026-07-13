from __future__ import annotations

import gzip
import hashlib
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from cwa_precipitation_grid import CwaPrecipitationGrid
from rainfall_grid_freshness import evaluate_precipitation_freshness


MAX_COMPRESSED_GRID_BYTES = 8 * 1024 * 1024
MAX_DECOMPRESSED_GRID_BYTES = 32 * 1024 * 1024
MAX_MANIFEST_BYTES = 2 * 1024 * 1024


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

    def update_manifest(self, grids: list[CwaPrecipitationGrid]) -> dict[str, Any]:
        if not grids:
            raise ValueError("at least one weather grid is required")
        frames: list[dict[str, Any]] = []
        latest: dict[str, dict[str, Any]] = {}
        for grid in grids:
            path = self.put(grid)
            stored_grid = load_weather_grid_snapshot(path)
            frame = _compact_frame(
                stored_grid,
                path.relative_to(self.root).as_posix(),
            )
            frames.append(frame)
            existing = latest.get(grid.grid_kind)
            if existing is None or _frame_recency(frame) > _frame_recency(existing):
                latest[grid.grid_kind] = frame
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
        manifest = {
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
        }
        self._atomic_json(self.root / "rainfall_grid_manifest.json", manifest)
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
        return {
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
        return payload

    def _safe_path(self, relative: Path) -> Path:
        destination = (self.root / relative).resolve()
        if self.root not in destination.parents:
            raise ValueError("weather grid path escapes store root")
        return destination

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
