from pathlib import Path

import pytest

from admin_local_raster_source import build_local_raster_source_manifest
from admin_local_raster_tiles import (
    LOCAL_RASTER_TILE_URL_TEMPLATE,
    build_local_raster_tile_proxy_contract,
    build_raster_tile_pyramid_plan,
    cut_raster_tile_pyramid,
    load_or_build_raster_tile_payload,
    raster_tile_cache_path,
    tile_bounds_wgs84,
)


def test_builds_raster_tile_plan_from_local_geotiff_manifest(tmp_path):
    source = tmp_path / "sample_wgs84.tiff"
    _write_sample_geotiff(source)
    source_manifest = build_local_raster_source_manifest(source)

    plan = build_raster_tile_pyramid_plan(
        source_manifest,
        cache_root=tmp_path / "raster-tiles",
        min_zoom=5,
        max_zoom=6,
    )

    assert plan["artifact_kind"] == "admin_local_raster_tile_pyramid_plan"
    assert plan["status"] == "planned_capacity_ok"
    assert plan["project_id"] == "chilai_nanhua_day1"
    assert plan["layer_id"] == "imagery"
    assert plan["cache_root"] == str(tmp_path / "raster-tiles")
    assert plan["runtime_tile_url_template"] == LOCAL_RASTER_TILE_URL_TEMPLATE
    assert plan["min_zoom"] == 5
    assert plan["max_zoom"] == 6
    assert plan["total_tile_count"] >= 1
    assert plan["within_capacity_limit"] is True
    assert plan["external_network_required"] is False
    assert plan["downloads_tiles_into_repo"] is False
    assert plan["raw_raster_committed_to_repo_allowed"] is False


def test_dry_run_does_not_write_tiles(tmp_path):
    source = tmp_path / "sample_wgs84.tiff"
    _write_sample_geotiff(source)
    source_manifest = build_local_raster_source_manifest(source)
    plan = build_raster_tile_pyramid_plan(
        source_manifest,
        cache_root=tmp_path / "raster-tiles",
        min_zoom=5,
        max_zoom=5,
    )

    summary = cut_raster_tile_pyramid(
        source_manifest,
        plan,
        dry_run=True,
        max_tiles=1,
    )

    assert summary["status"] == "dry_run_ready"
    assert summary["tiles_seen"] == 1
    assert summary["tiles_written"] == 0
    assert not list((tmp_path / "raster-tiles").glob("**/*.png"))


def test_cuts_local_geotiff_into_png_tile_cache(tmp_path):
    source = tmp_path / "sample_wgs84.tiff"
    _write_sample_geotiff(source)
    source_manifest = build_local_raster_source_manifest(source)
    plan = build_raster_tile_pyramid_plan(
        source_manifest,
        cache_root=tmp_path / "raster-tiles",
        min_zoom=5,
        max_zoom=5,
    )

    summary = cut_raster_tile_pyramid(
        source_manifest,
        plan,
        dry_run=False,
        max_tiles=1,
    )

    assert summary["status"] == "seed_complete"
    assert summary["tiles_written"] == 1
    written_tiles = list((tmp_path / "raster-tiles").glob("**/*.png"))
    assert len(written_tiles) == 1
    assert written_tiles[0].read_bytes().startswith(b"\x89PNG\r\n\x1a\n")

    try:
        from PIL import Image
    except Exception as exc:  # pragma: no cover - environment guard
        pytest.skip(f"Pillow is unavailable: {exc}")
    with Image.open(written_tiles[0]) as image:
        assert image.size == (256, 256)
        assert image.mode == "RGBA"


def test_raster_tile_proxy_serves_cached_png_and_transparent_fallback(tmp_path):
    cached_path = raster_tile_cache_path(
        "chilai_nanhua_day1",
        "imagery",
        5,
        26,
        13,
        cache_root=tmp_path,
    )
    cached_path.parent.mkdir(parents=True)
    cached_path.write_bytes(b"\x89PNG\r\n\x1a\nraster-demo-tile")

    payload = load_or_build_raster_tile_payload(
        "chilai_nanhua_day1",
        "imagery",
        5,
        26,
        13,
        cache_root=tmp_path,
    )

    assert payload.media_type == "image/png"
    assert payload.source == "local_cache"
    assert payload.body == cached_path.read_bytes()
    assert payload.headers()["X-Scout-Tile-Source"] == "local_cache"
    assert payload.headers()["Cache-Control"] == "no-cache, max-age=0, must-revalidate"

    fallback = load_or_build_raster_tile_payload(
        "chilai_nanhua_day1",
        "imagery",
        5,
        26,
        14,
        cache_root=tmp_path,
    )
    assert fallback.media_type == "image/png"
    assert fallback.source == "transparent_fallback"
    assert b"Raster offline" not in fallback.body
    assert fallback.body.startswith(b"\x89PNG\r\n\x1a\n")
    assert fallback.headers()["Cache-Control"] == "no-store"


def test_raster_tile_proxy_contract_and_validation(tmp_path):
    contract = build_local_raster_tile_proxy_contract(cache_root=tmp_path)

    assert contract["artifact_kind"] == "admin_local_raster_tile_proxy_contract"
    assert contract["status"] == "local_proxy_ready"
    assert contract["url_template"] == LOCAL_RASTER_TILE_URL_TEMPLATE
    assert contract["cache_policy"] == "local_file_cache_then_transparent_fallback"
    assert contract["external_network_fetch_allowed"] is False
    assert contract["downloads_tiles_into_repo"] is False

    with pytest.raises(ValueError):
        raster_tile_cache_path("../bad", "imagery", 5, 26, 13, cache_root=tmp_path)
    with pytest.raises(ValueError):
        load_or_build_raster_tile_payload(
            "chilai_nanhua_day1",
            "imagery",
            21,
            0,
            0,
            cache_root=tmp_path,
        )
    with pytest.raises(FileNotFoundError):
        load_or_build_raster_tile_payload(
            "chilai_nanhua_day1",
            "imagery",
            5,
            26,
            14,
            cache_root=tmp_path,
            fallback_enabled=False,
        )


def test_tile_bounds_are_wgs84_slippy_bounds():
    bounds = tile_bounds_wgs84(0, 0, 0)

    assert bounds["west"] == pytest.approx(-180.0)
    assert bounds["east"] == pytest.approx(180.0)
    assert bounds["north"] == pytest.approx(85.05112878)
    assert bounds["south"] == pytest.approx(-85.05112878)


def _write_sample_geotiff(path: Path) -> None:
    try:
        from PIL import Image, TiffImagePlugin
    except Exception as exc:  # pragma: no cover - environment guard
        pytest.skip(f"Pillow is unavailable: {exc}")

    image = Image.new("RGB", (64, 48), color=(20, 80, 140))
    tags = TiffImagePlugin.ImageFileDirectory_v2()
    tags[33550] = (0.001, 0.001, 0.0)
    tags[33922] = (0.0, 0.0, 0.0, 121.0, 24.0, 0.0)
    tags[34735] = (
        1,
        1,
        0,
        4,
        1024,
        0,
        1,
        2,
        1025,
        0,
        1,
        1,
        2048,
        0,
        1,
        4326,
        2049,
        34737,
        7,
        0,
    )
    tags[34737] = "WGS 84|"
    image.save(path, format="TIFF", tiffinfo=tags)
