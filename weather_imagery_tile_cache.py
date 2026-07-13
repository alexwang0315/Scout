from __future__ import annotations

import hashlib
import io
import json
from math import asin, atan, atan2, cos, degrees, pi, radians, sin, sinh, sqrt, tan
import os
import time
import warnings
from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
from pathlib import Path
from typing import Any

from cwa_imagery_registry import ImageryProductSpec


DEFAULT_MAX_FRAME_BYTES = 8 * 1024 * 1024
DEFAULT_MAX_SOURCE_IMAGE_PIXELS = 20_000_000
DEFAULT_CACHE_MAX_BYTES = 2 * 1024 * 1024 * 1024
DEFAULT_CACHE_MAX_AGE_HOURS = 72


@dataclass(frozen=True)
class CachedImageryFrame:
    frame_id: str
    product_id: str
    source_timestamp: str
    fetched_at: str
    image_type: str
    extent: str
    expected_delay_minutes: int
    update_interval_minutes: int
    bbox_wgs84: dict[str, float]
    media_type: str
    dimensions: tuple[int, int]
    sha256: str
    cache_ref: str
    display_ref: str | None
    display_media_type: str | None
    etag: str | None
    georeference_version: str
    sampling_role: str
    map_overlay_supported: bool
    route_sampling_supported: bool
    processing_target: str = "server_side_job"

    def to_dict(self) -> dict[str, Any]:
        return {
            "frameId": self.frame_id,
            "productId": self.product_id,
            "sourceTimestamp": self.source_timestamp,
            "fetchedAt": self.fetched_at,
            "imageType": self.image_type,
            "extent": self.extent,
            "expectedDelayMinutes": self.expected_delay_minutes,
            "updateIntervalMinutes": self.update_interval_minutes,
            "bboxWgs84": self.bbox_wgs84,
            "mediaType": self.media_type,
            "dimensions": {"width": self.dimensions[0], "height": self.dimensions[1]},
            "sha256": self.sha256,
            "cacheRef": self.cache_ref,
            "displayRef": self.display_ref,
            "displayMediaType": self.display_media_type,
            "etag": self.etag,
            "georeferenceVersion": self.georeference_version,
            "samplingRole": self.sampling_role,
            "mapOverlaySupported": self.map_overlay_supported,
            "routeSamplingSupported": self.route_sampling_supported,
            "processingTarget": self.processing_target,
            "raspberryPiImageProcessing": False,
            "mobileImageProcessing": False,
            "candidateOnly": True,
            "runtimeSafetyTruth": False,
        }


class WeatherImageryTileCache:
    def __init__(
        self,
        root: Path | str,
        *,
        max_total_bytes: int = DEFAULT_CACHE_MAX_BYTES,
        max_age_hours: int = DEFAULT_CACHE_MAX_AGE_HOURS,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.max_total_bytes = max(1, int(max_total_bytes))
        self.max_age_hours = max(1, int(max_age_hours))

    def put_frame(
        self,
        spec: ImageryProductSpec,
        *,
        source_timestamp: str,
        fetched_at: str,
        content: bytes,
        media_type: str,
        dimensions: tuple[int, int],
        etag: str | None = None,
        build_display_asset: bool = True,
        display_max_dimension: int = 1024,
        bbox_wgs84: dict[str, float] | None = None,
    ) -> CachedImageryFrame:
        if not content:
            raise ValueError("imagery frame content is empty")
        if media_type not in {"image/png", "image/jpeg"}:
            raise ValueError(f"unsupported imagery media type: {media_type}")
        if len(content) > DEFAULT_MAX_FRAME_BYTES:
            raise ValueError("imagery frame exceeds cache byte limit")
        self.prune(reserve_bytes=len(content) * 2)
        sha256 = hashlib.sha256(content).hexdigest()
        timestamp_key = _timestamp_key(source_timestamp)
        extension = ".png" if media_type == "image/png" else ".jpg"
        frame_id = f"{spec.product_id}.{timestamp_key}.{sha256[:12]}"
        relative_dir = Path("frames") / _safe_component(spec.product_id) / timestamp_key
        raw_ref = (relative_dir / f"{sha256}{extension}").as_posix()
        raw_path = self._resolve_ref(raw_ref)
        _atomic_write(raw_path, content)

        display_ref: str | None = None
        display_media_type: str | None = None
        if build_display_asset:
            display_ref, display_media_type = self._build_display_asset(
                spec=spec,
                relative_dir=relative_dir,
                sha256=sha256,
                content=content,
                media_type=media_type,
                max_dimension=display_max_dimension,
            )
        effective_bbox = dict(bbox_wgs84 or spec.bbox_wgs84.to_dict())
        if (
            display_ref is not None
            and "fixed_grid_reprojection_required" in spec.georeference_version
        ):
            effective_bbox = {
                "west": 60.0,
                "south": -85.05112878,
                "east": 240.0,
                "north": 85.05112878,
            }
        frame = CachedImageryFrame(
            frame_id=frame_id,
            product_id=spec.product_id,
            source_timestamp=source_timestamp,
            fetched_at=fetched_at,
            image_type=spec.image_type,
            extent=spec.extent,
            expected_delay_minutes=spec.expected_delay_minutes,
            update_interval_minutes=spec.update_interval_minutes,
            bbox_wgs84=effective_bbox,
            media_type=media_type,
            dimensions=dimensions,
            sha256=sha256,
            cache_ref=raw_ref,
            display_ref=display_ref,
            display_media_type=display_media_type,
            etag=etag,
            georeference_version=spec.georeference_version,
            sampling_role=spec.sampling_role,
            map_overlay_supported=(
                spec.map_overlay_supported
                and (
                    "fixed_grid_reprojection_required" not in spec.georeference_version
                    or display_ref is not None
                )
            ),
            route_sampling_supported=spec.route_sampling_supported,
        )
        metadata_ref = (relative_dir / f"{sha256}.json").as_posix()
        _atomic_write(
            self._resolve_ref(metadata_ref),
            (
                json.dumps(
                    frame.to_dict(), ensure_ascii=False, indent=2, sort_keys=True
                )
                + "\n"
            ).encode("utf-8"),
        )
        self.prune()
        return frame

    def get_frame(self, frame_id: str) -> CachedImageryFrame | None:
        for path in self.root.glob("frames/*/*/*.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if payload.get("frameId") != frame_id:
                continue
            return _frame_from_dict(payload)
        return None

    def list_frames(self, product_id: str) -> list[CachedImageryFrame]:
        frames: dict[str, CachedImageryFrame] = {}
        product_component = _safe_component(product_id)
        for path in self.root.glob(f"frames/{product_component}/*/*.json"):
            try:
                frame = _frame_from_dict(json.loads(path.read_text(encoding="utf-8")))
            except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
                continue
            if frame.product_id == product_id:
                frames[frame.frame_id] = frame
        return sorted(frames.values(), key=lambda item: item.source_timestamp)

    def get_frame_for_source(
        self,
        product_id: str,
        source_timestamp: str,
    ) -> CachedImageryFrame | None:
        return next(
            (
                frame
                for frame in reversed(self.list_frames(product_id))
                if frame.source_timestamp == source_timestamp
            ),
            None,
        )

    def read_asset(self, cache_ref: str) -> bytes:
        path = self._resolve_ref(cache_ref)
        if not path.is_file():
            raise FileNotFoundError(cache_ref)
        return path.read_bytes()

    def asset_path(self, cache_ref: str) -> Path:
        path = self._resolve_ref(cache_ref)
        if not path.is_file():
            raise FileNotFoundError(cache_ref)
        return path

    def asset_exists(self, cache_ref: str) -> bool:
        return self._resolve_ref(cache_ref).is_file()

    def prune(self, *, reserve_bytes: int = 0) -> dict[str, int]:
        cutoff = time.time() - self.max_age_hours * 3600
        removed_files = 0
        removed_bytes = 0

        # Metadata is the frame-bundle index. Expiring it must remove every
        # referenced asset in the same operation so a manifest cannot retain a
        # half-deleted frame.
        for metadata_path in self.root.glob("frames/*/*/*.json"):
            try:
                metadata_stat = metadata_path.stat()
            except OSError:
                continue
            if metadata_stat.st_mtime >= cutoff:
                continue
            try:
                payload = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                payload = {}
            bundle_paths = [metadata_path]
            for key in ("cacheRef", "displayRef"):
                ref = payload.get(key) if isinstance(payload, dict) else None
                if isinstance(ref, str) and ref:
                    try:
                        bundle_paths.append(self._resolve_ref(ref))
                    except ValueError:
                        continue
            for path in dict.fromkeys(bundle_paths):
                try:
                    size = path.stat().st_size
                    path.unlink()
                    removed_files += 1
                    removed_bytes += size
                except OSError:
                    continue

        bundles: list[tuple[float, int, Path]] = []
        total_bytes = 0
        for directory in self.root.glob("frames/*/*"):
            if not directory.is_dir():
                continue
            stats: list[tuple[float, int]] = []
            for path in directory.iterdir():
                if not path.is_file():
                    continue
                try:
                    stat = path.stat()
                except OSError:
                    continue
                stats.append((stat.st_mtime, stat.st_size))
            if not stats:
                try:
                    directory.rmdir()
                except OSError:
                    pass
                continue
            bundle_bytes = sum(size for _mtime, size in stats)
            bundles.append(
                (max(mtime for mtime, _size in stats), bundle_bytes, directory)
            )
            total_bytes += bundle_bytes
        target = max(0, self.max_total_bytes - max(0, reserve_bytes))
        for _mtime, size, directory in sorted(bundles):
            if total_bytes <= target:
                break
            bundle_removed = 0
            bundle_files = 0
            for path in directory.iterdir():
                if not path.is_file():
                    continue
                try:
                    path_size = path.stat().st_size
                    path.unlink()
                    bundle_removed += path_size
                    bundle_files += 1
                except OSError:
                    continue
            try:
                directory.rmdir()
            except OSError:
                pass
            total_bytes -= bundle_removed
            removed_files += bundle_files
            removed_bytes += bundle_removed
        return {"removedFiles": removed_files, "removedBytes": removed_bytes}

    @contextmanager
    def server_job_guard(self, *, min_interval_seconds: int = 30):
        """Serialize heavy jobs and reject accidental rapid re-runs."""
        lock_path = self.root / ".server-job.lock"
        completed_path = self.root / ".server-job-completed-at"
        with lock_path.open("a+", encoding="utf-8") as lock_file:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeError(
                    "a CWA imagery server job is already running"
                ) from exc
            try:
                try:
                    completed_at = float(completed_path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    completed_at = 0.0
                if time.time() - completed_at < max(0, min_interval_seconds):
                    raise RuntimeError("CWA imagery server job rate limit is active")
                yield
            finally:
                _atomic_write(completed_path, str(time.time()).encode("ascii"))
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _resolve_ref(self, cache_ref: str) -> Path:
        if not cache_ref or Path(cache_ref).is_absolute():
            raise ValueError("unsafe cache ref")
        path = (self.root / cache_ref).resolve()
        try:
            path.relative_to(self.root)
        except ValueError as exc:
            raise ValueError("unsafe cache ref") from exc
        return path

    def _build_display_asset(
        self,
        *,
        spec: ImageryProductSpec,
        relative_dir: Path,
        sha256: str,
        content: bytes,
        media_type: str,
        max_dimension: int,
    ) -> tuple[str | None, str | None]:
        try:
            from PIL import Image
        except ImportError:
            return None, None
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            image = Image.open(io.BytesIO(content))
            if image.width * image.height > DEFAULT_MAX_SOURCE_IMAGE_PIXELS:
                image.close()
                raise ValueError("CWA imagery source exceeds pixel limit")
            image.load()
            if "fixed_grid_reprojection_required" in spec.georeference_version:
                reprojected = _reproject_himawari_full_disk(image)
                image.close()
                display_ref = (relative_dir / f"{sha256}.display.png").as_posix()
                buffer = io.BytesIO()
                reprojected.save(buffer, format="PNG", optimize=True)
                reprojected.close()
                _atomic_write(self._resolve_ref(display_ref), buffer.getvalue())
                return display_ref, "image/png"
            image.thumbnail((max_dimension, max_dimension))
            extension = ".png" if media_type == "image/png" else ".jpg"
            display_ref = (relative_dir / f"{sha256}.display{extension}").as_posix()
            display_path = self._resolve_ref(display_ref)
            buffer = io.BytesIO()
            output_format = "PNG" if media_type == "image/png" else "JPEG"
            if output_format == "JPEG" and image.mode not in {"RGB", "L"}:
                image = image.convert("RGB")
            image.save(buffer, format=output_format, optimize=True)
            _atomic_write(display_path, buffer.getvalue())
            image.close()
            return display_ref, media_type


def _frame_from_dict(payload: dict[str, Any]) -> CachedImageryFrame:
    dimensions = payload.get("dimensions") or {}
    return CachedImageryFrame(
        frame_id=str(payload["frameId"]),
        product_id=str(payload["productId"]),
        source_timestamp=str(payload["sourceTimestamp"]),
        fetched_at=str(payload["fetchedAt"]),
        image_type=str(payload["imageType"]),
        extent=str(payload["extent"]),
        expected_delay_minutes=int(payload["expectedDelayMinutes"]),
        update_interval_minutes=int(payload.get("updateIntervalMinutes", 10)),
        bbox_wgs84=dict(payload["bboxWgs84"]),
        media_type=str(payload["mediaType"]),
        dimensions=(int(dimensions.get("width", 0)), int(dimensions.get("height", 0))),
        sha256=str(payload["sha256"]),
        cache_ref=str(payload["cacheRef"]),
        display_ref=payload.get("displayRef"),
        display_media_type=payload.get("displayMediaType"),
        etag=payload.get("etag"),
        georeference_version=str(payload.get("georeferenceVersion") or "unknown"),
        sampling_role=str(payload.get("samplingRole") or "visual"),
        map_overlay_supported=bool(payload.get("mapOverlaySupported", True)),
        route_sampling_supported=bool(payload.get("routeSamplingSupported", True)),
    )


def _safe_component(value: str) -> str:
    normalized = "".join(
        char if char.isalnum() or char in "._-" else "_" for char in value
    )
    if not normalized or normalized in {".", ".."}:
        raise ValueError("unsafe cache component")
    return normalized


def _timestamp_key(value: str) -> str:
    return _safe_component(value.replace(":", "").replace("+", "_"))


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_bytes(content)
    temp.replace(path)


def _reproject_himawari_full_disk(image: Any, *, output_size: int = 400) -> Any:
    """Reproject a Himawari geostationary disk into an RGBA WGS84 grid."""
    from PIL import Image

    source = image.convert("RGB")
    center_x, center_y, radius_x, radius_y = _detect_full_disk_geometry(source)
    target = Image.new("RGBA", (output_size, output_size), (0, 0, 0, 0))
    target_pixels = target.load()
    source_pixels = source.load()
    equatorial_radius_km = 6378.137
    polar_radius_km = 6356.7523
    satellite_radius_km = 42164.0
    sub_satellite_lon = radians(140.7)
    max_x_angle = asin(equatorial_radius_km / satellite_radius_km)
    max_y_angle = asin(polar_radius_km / satellite_radius_km)
    eccentricity = (
        equatorial_radius_km**2 - polar_radius_km**2
    ) / equatorial_radius_km**2
    for y in range(output_size):
        latitude = radians(_web_mercator_latitude_for_row(y, output_size))
        geocentric_latitude = atan(
            (polar_radius_km**2 / equatorial_radius_km**2) * tan(latitude)
        )
        cos_latitude = cos(geocentric_latitude)
        earth_radius = polar_radius_km / sqrt(1.0 - eccentricity * cos_latitude**2)
        earth_z = earth_radius * sin(geocentric_latitude)
        for x in range(output_size):
            longitude = radians(60.0 + (x + 0.5) * 180.0 / output_size)
            delta_lon = (longitude - sub_satellite_lon + pi) % (2 * pi) - pi
            earth_x = earth_radius * cos_latitude * cos(delta_lon)
            earth_y = earth_radius * cos_latitude * sin(delta_lon)
            if satellite_radius_km * earth_x / equatorial_radius_km**2 <= 1.0:
                continue
            scan_x = atan2(earth_y, satellite_radius_km - earth_x)
            scan_y = atan2(
                earth_z,
                sqrt((satellite_radius_km - earth_x) ** 2 + earth_y**2),
            )
            source_x = round(center_x + scan_x / max_x_angle * radius_x)
            source_y = round(center_y - scan_y / max_y_angle * radius_y)
            if 0 <= source_x < source.width and 0 <= source_y < source.height:
                red, green, blue = source_pixels[source_x, source_y]
                target_pixels[x, y] = (red, green, blue, 255)
    source.close()
    return target


def _web_mercator_latitude_for_row(row: int, output_size: int) -> float:
    mercator_y = pi * (1.0 - 2.0 * (row + 0.5) / output_size)
    return degrees(atan(sinh(mercator_y)))


def _detect_full_disk_geometry(image: Any) -> tuple[float, float, float, float]:
    scale = min(1.0, 512.0 / max(image.width, image.height))
    sample_width = max(1, round(image.width * scale))
    sample_height = max(1, round(image.height * scale))
    sample = image.resize((sample_width, sample_height))
    pixels = sample.load()
    row_counts = [
        sum(1 for x in range(sample.width) if max(pixels[x, y]) >= 18)
        for y in range(sample.height)
    ]
    column_counts = [
        sum(1 for y in range(sample.height) if max(pixels[x, y]) >= 18)
        for x in range(sample.width)
    ]
    rows = [
        index for index, count in enumerate(row_counts) if count >= sample.width * 0.15
    ]
    columns = [
        index
        for index, count in enumerate(column_counts)
        if count >= sample.height * 0.15
    ]
    if not rows or not columns:
        sample.close()
        raise ValueError("unable to detect Himawari full-disk geometry")
    left, right = min(columns), max(columns)
    top, bottom = min(rows), max(rows)
    result = (
        ((left + right) / 2.0) * image.width / sample.width,
        ((top + bottom) / 2.0) * image.height / sample.height,
        max(1.0, (right - left) / 2.0) * image.width / sample.width,
        max(1.0, (bottom - top) / 2.0) * image.height / sample.height,
    )
    sample.close()
    return result
