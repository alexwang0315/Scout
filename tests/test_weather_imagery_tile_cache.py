import io
import json
from math import asinh, pi, radians, tan
import os
from pathlib import Path
import time

import pytest

from cwa_imagery_registry import build_cwa_imagery_registry
from weather_imagery_tile_cache import (
    WeatherImageryTileCache,
    _web_mercator_latitude_for_row,
)


def test_cache_stores_content_addressed_georeferenced_frame(tmp_path: Path) -> None:
    spec = build_cwa_imagery_registry()["radar.integrated.taiwan.transparent"]
    cache = WeatherImageryTileCache(tmp_path / "cache")

    frame = cache.put_frame(
        spec,
        source_timestamp="2026-07-11T03:20:00Z",
        fetched_at="2026-07-11T03:27:00Z",
        content=b"small-fixture-image",
        media_type="image/png",
        dimensions=(4, 4),
        etag="fixture-etag",
        build_display_asset=False,
    )

    assert frame.source_timestamp == "2026-07-11T03:20:00Z"
    assert frame.fetched_at == "2026-07-11T03:27:00Z"
    assert frame.image_type == "echo_no_terrain"
    assert frame.extent == "taiwan"
    assert frame.expected_delay_minutes == spec.expected_delay_minutes
    assert frame.update_interval_minutes == spec.update_interval_minutes
    assert frame.cache_ref.endswith(".png")
    assert cache.read_asset(frame.cache_ref) == b"small-fixture-image"
    assert cache.asset_exists(frame.cache_ref) is True
    assert cache.asset_exists("frames/missing.png") is False
    assert frame.to_dict()["sourceTimestamp"] == "2026-07-11T03:20:00Z"
    assert frame.to_dict()["fetchedAt"] == "2026-07-11T03:27:00Z"
    assert frame.to_dict()["updateIntervalMinutes"] == spec.update_interval_minutes


def test_cache_prunes_an_expired_frame_as_one_bundle(tmp_path: Path) -> None:
    spec = build_cwa_imagery_registry()["radar.integrated.taiwan.transparent"]
    cache = WeatherImageryTileCache(tmp_path / "cache", max_age_hours=1)
    frame = cache.put_frame(
        spec,
        source_timestamp="2026-07-11T03:20:00Z",
        fetched_at="2026-07-11T03:27:00Z",
        content=b"bundle-image",
        media_type="image/png",
        dimensions=(4, 4),
        build_display_asset=False,
    )
    metadata_path = next(cache.root.glob("frames/*/*/*.json"))
    expired = time.time() - 7_200
    os.utime(metadata_path, (expired, expired))

    cache.prune()

    assert cache.get_frame(frame.frame_id) is None
    assert list(metadata_path.parent.glob("*")) == []


def test_prune_tolerates_invalid_metadata_unsafe_refs_and_unlink_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = WeatherImageryTileCache(tmp_path / "cache", max_age_hours=1)
    expired = time.time() - 7_200

    invalid_dir = cache.root / "frames/fixture/invalid"
    invalid_dir.mkdir(parents=True)
    invalid_metadata = invalid_dir / "invalid.json"
    invalid_metadata.write_text("not-json", encoding="utf-8")
    os.utime(invalid_metadata, (expired, expired))

    unsafe_dir = cache.root / "frames/fixture/unsafe"
    unsafe_dir.mkdir(parents=True)
    unsafe_metadata = unsafe_dir / "unsafe.json"
    unsafe_metadata.write_text(
        json.dumps({"cacheRef": "../outside-cache.png"}),
        encoding="utf-8",
    )
    os.utime(unsafe_metadata, (expired, expired))

    failure_dir = cache.root / "frames/fixture/unlink-failure"
    failure_dir.mkdir(parents=True)
    stubborn_asset = failure_dir / "stubborn.png"
    stubborn_asset.write_bytes(b"stubborn")
    failure_metadata = failure_dir / "frame.json"
    failure_metadata.write_text(
        json.dumps(
            {
                "cacheRef": stubborn_asset.relative_to(cache.root).as_posix(),
            }
        ),
        encoding="utf-8",
    )
    os.utime(failure_metadata, (expired, expired))

    original_unlink = Path.unlink

    def unlink_with_failure(path: Path, *args: object, **kwargs: object) -> None:
        if path == stubborn_asset:
            raise OSError("simulated unlink failure")
        original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", unlink_with_failure)

    result = cache.prune()

    assert result["removedFiles"] == 3
    assert not invalid_metadata.exists()
    assert not unsafe_metadata.exists()
    assert not failure_metadata.exists()
    assert stubborn_asset.read_bytes() == b"stubborn"


def test_prune_tolerates_non_files_stat_errors_and_nonempty_directories(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = WeatherImageryTileCache(tmp_path / "cache")
    bundle_dir = cache.root / "frames/fixture/scan-errors"
    bundle_dir.mkdir(parents=True)
    (bundle_dir / "nested").mkdir()
    unreadable_file = bundle_dir / "unreadable.bin"
    unreadable_file.write_bytes(b"unreadable")

    original_is_file = Path.is_file
    original_stat = Path.stat

    def is_file_for_scan(path: Path) -> bool:
        if path == unreadable_file:
            return True
        return original_is_file(path)

    def stat_with_failure(path: Path, *args: object, **kwargs: object):
        if path == unreadable_file:
            raise OSError("simulated stat failure")
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "is_file", is_file_for_scan)
    monkeypatch.setattr(Path, "stat", stat_with_failure)

    result = cache.prune()

    assert result == {"removedFiles": 0, "removedBytes": 0}
    assert unreadable_file.read_bytes() == b"unreadable"


def test_prune_capacity_eviction_counts_partial_success_and_continues_on_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = WeatherImageryTileCache(tmp_path / "cache", max_total_bytes=1)
    bundle_dir = cache.root / "frames/fixture/capacity"
    bundle_dir.mkdir(parents=True)
    removable_asset = bundle_dir / "removable.bin"
    removable_asset.write_bytes(b"remove-me")
    stubborn_asset = bundle_dir / "stubborn.bin"
    stubborn_asset.write_bytes(b"keep-me")
    (bundle_dir / "nested").mkdir()

    original_unlink = Path.unlink

    def unlink_with_failure(path: Path, *args: object, **kwargs: object) -> None:
        if path == stubborn_asset:
            raise OSError("simulated unlink failure")
        original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", unlink_with_failure)

    result = cache.prune()

    assert result == {
        "removedFiles": 1,
        "removedBytes": len(b"remove-me"),
    }
    assert not removable_asset.exists()
    assert stubborn_asset.read_bytes() == b"keep-me"


def test_cache_rejects_traversal_and_never_fetches_on_read(tmp_path: Path) -> None:
    cache = WeatherImageryTileCache(tmp_path / "cache")

    with pytest.raises(ValueError, match="unsafe cache ref"):
        cache.read_asset("../secret")

    assert cache.get_frame("missing-frame") is None


def test_server_job_guard_serializes_and_rate_limits(tmp_path: Path) -> None:
    cache = WeatherImageryTileCache(tmp_path / "cache")
    with cache.server_job_guard(min_interval_seconds=30):
        with pytest.raises(RuntimeError, match="already running"):
            with cache.server_job_guard(min_interval_seconds=30):
                pass
    with pytest.raises(RuntimeError, match="rate limit"):
        with cache.server_job_guard(min_interval_seconds=30):
            pass


def test_full_disk_requires_server_reprojection_and_is_not_route_sampled() -> None:
    spec = build_cwa_imagery_registry()["satellite.enhanced_color.full_disk"]

    assert spec.available is True
    assert spec.map_overlay_supported is True
    assert spec.route_sampling_supported is False
    assert "fixed_grid_reprojection_required" in spec.georeference_version


def test_full_disk_builds_transparent_wgs84_png_overlay(tmp_path: Path) -> None:
    from PIL import Image, ImageDraw

    spec = build_cwa_imagery_registry()["satellite.enhanced_color.full_disk"]
    source = Image.new("RGB", (100, 100), "black")
    ImageDraw.Draw(source).ellipse((3, 3, 97, 97), fill=(20, 120, 220))
    buffer = io.BytesIO()
    source.save(buffer, format="JPEG")
    cache = WeatherImageryTileCache(tmp_path / "cache")

    frame = cache.put_frame(
        spec,
        source_timestamp="2026-07-11T22:30:00+08:00",
        fetched_at="2026-07-11T22:35:00+08:00",
        content=buffer.getvalue(),
        media_type="image/jpeg",
        dimensions=(100, 100),
        build_display_asset=True,
    )

    assert frame.display_ref is not None
    assert frame.display_ref.endswith(".png")
    assert frame.display_media_type == "image/png"
    assert frame.map_overlay_supported is True
    assert frame.bbox_wgs84 == {
        "west": 60.0,
        "south": -85.05112878,
        "east": 240.0,
        "north": 85.05112878,
    }
    with Image.open(io.BytesIO(cache.read_asset(frame.display_ref))) as overlay:
        assert overlay.mode == "RGBA"
        assert overlay.size == (400, 400)
        assert overlay.getpixel((0, 0))[3] == 0


def test_full_disk_rows_align_with_admin_web_mercator_projection() -> None:
    size = 400
    taiwan_latitude = 24.0
    mercator_y = asinh(tan(radians(taiwan_latitude)))
    row = round((1.0 - mercator_y / pi) * size / 2.0 - 0.5)

    assert abs(_web_mercator_latitude_for_row(row, size) - taiwan_latitude) < 0.3


def test_failed_server_job_also_triggers_cooldown(tmp_path: Path) -> None:
    cache = WeatherImageryTileCache(tmp_path / "cache")
    with pytest.raises(ValueError, match="fixture failure"):
        with cache.server_job_guard(min_interval_seconds=30):
            raise ValueError("fixture failure")
    with pytest.raises(RuntimeError, match="rate limit"):
        with cache.server_job_guard(min_interval_seconds=30):
            pass
