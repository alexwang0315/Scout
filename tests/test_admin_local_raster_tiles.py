import io
from pathlib import Path

import pytest

from admin_local_raster_source import build_local_raster_source_manifest
from admin_imagery_sources import RemoteImageryTile, imagery_source_for_project
from admin_local_raster_tiles import (
    LOCAL_RASTER_TILE_URL_TEMPLATE,
    build_imagery_tile_cache_plan,
    build_local_raster_tile_proxy_contract,
    build_raster_tile_pyramid_plan,
    cut_raster_tile_pyramid,
    load_or_build_raster_tile_payload,
    raster_tile_cache_path,
    seed_imagery_tile_cache,
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


def test_builds_wmts_imagery_tile_cache_plan_without_raw_urls(tmp_path):
    source = imagery_source_for_project({"imagery_source_id": "happyman_rudy"})

    plan = build_imagery_tile_cache_plan(
        {
            "west": 121.2,
            "south": 24.03,
            "east": 121.21,
            "north": 24.04,
        },
        project_id="chilai_nanhua_day1",
        layer_id="rudy",
        imagery_source=source,
        cache_root=tmp_path / "imagery-tiles",
        min_zoom=12,
        max_zoom=13,
    )

    assert plan["artifact_kind"] == "admin_imagery_tile_cache_plan"
    assert plan["status"] == "planned_capacity_ok"
    assert plan["source_id"] == "happyman_rudy"
    assert plan["source_kind"] == "wmts_kvp_tile"
    assert plan["source_metadata"]["wmts_layer"] == "rudy"
    assert plan["source_metadata"]["wmts_tile_matrix_set"] == "gm_grid"
    assert plan["raw_source_url_embedded"] is False
    assert plan["zoom_range"] == "12-13"
    assert [item["z"] for item in plan["zoom_ranges"]] == [12, 13]
    assert plan["total_tile_count"] >= 2
    assert plan["runtime_tile_url_template"] == LOCAL_RASTER_TILE_URL_TEMPLATE
    assert plan["external_network_required"] is True
    assert plan["downloads_tiles_into_repo"] is False


def test_seeds_wmts_imagery_tile_cache_with_fixture_fetcher(tmp_path):
    source = imagery_source_for_project({"imagery_source_id": "happyman_rudy"})
    plan = build_imagery_tile_cache_plan(
        {
            "west": 121.2,
            "south": 24.03,
            "east": 121.2,
            "north": 24.03,
        },
        project_id="chilai_nanhua_day1",
        layer_id="rudy",
        imagery_source=source,
        cache_root=tmp_path / "imagery-tiles",
        min_zoom=12,
        max_zoom=12,
    )
    calls = []

    def fake_fetch(imagery_source, z, x, y):
        calls.append((imagery_source["source_id"], z, x, y))
        return RemoteImageryTile(
            body=b"\x89PNG\r\n\x1a\nwmts-fixture",
            media_type="image/png",
            source_id=imagery_source["source_id"],
            url="https://example.test/wmts",
            body_sha256="fixture-hash",
        )

    summary = seed_imagery_tile_cache(
        plan,
        imagery_source=source,
        provider_allows_offline_prefetch=True,
        dry_run=False,
        fetch_tile=fake_fetch,
    )

    assert summary["status"] == "seed_complete"
    assert summary["tiles_seen"] == 1
    assert summary["tiles_written"] == 1
    assert calls
    tile = plan["zoom_ranges"][0]
    cached_path = raster_tile_cache_path(
        "chilai_nanhua_day1",
        "rudy",
        12,
        tile["x_min"],
        tile["y_min"],
        cache_root=tmp_path / "imagery-tiles",
    )
    assert cached_path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


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


def test_raster_tile_proxy_detects_cached_jpeg_media_type(tmp_path):
    cached_path = raster_tile_cache_path(
        "chilai_nanhua_day1",
        "imagery",
        5,
        26,
        13,
        cache_root=tmp_path,
    )
    cached_path.parent.mkdir(parents=True)
    cached_path.write_bytes(b"\xff\xd8\xff\xe0remote-jpeg-tile")

    payload = load_or_build_raster_tile_payload(
        "chilai_nanhua_day1",
        "imagery",
        5,
        26,
        13,
        cache_root=tmp_path,
    )

    assert payload.media_type == "image/jpeg"
    assert payload.source == "local_cache"


def test_raster_tile_proxy_serves_cropped_parent_cache_fallback(tmp_path):
    try:
        from PIL import Image
    except Exception as exc:  # pragma: no cover - environment guard
        pytest.skip(f"Pillow is unavailable: {exc}")

    parent_path = raster_tile_cache_path(
        "chilai_nanhua_day1",
        "imagery",
        1,
        1,
        1,
        cache_root=tmp_path,
    )
    parent_path.parent.mkdir(parents=True)
    parent_path.write_bytes(_quadrant_png())

    payload = load_or_build_raster_tile_payload(
        "chilai_nanhua_day1",
        "imagery",
        2,
        3,
        2,
        cache_root=tmp_path,
    )

    assert payload.source == "local_parent_cache_fallback"
    assert payload.media_type == "image/png"
    assert payload.cache_path == raster_tile_cache_path(
        "chilai_nanhua_day1",
        "imagery",
        2,
        3,
        2,
        cache_root=tmp_path,
    )
    assert payload.headers()["Cache-Control"] == "no-store"
    with Image.open(io.BytesIO(payload.body)) as image:
        assert image.size == (256, 256)
        assert image.convert("RGBA").getpixel((128, 128))[:3] == (0, 255, 0)


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


def test_raster_tile_proxy_can_fill_cache_from_explicit_imagery_source(tmp_path):
    source = imagery_source_for_project({"imagery_source_id": "nlsc_photo2"})
    remote_body = b"\x89PNG\r\n\x1a\nremote-imagery"

    def fake_fetcher(imagery_source, z, x, y, *, timeout_seconds):
        assert imagery_source["source_id"] == "nlsc_photo2"
        assert (z, x, y) == (5, 26, 13)
        assert timeout_seconds == 1.5
        return RemoteImageryTile(
            body=remote_body,
            media_type="image/png",
            source_id="nlsc_photo2",
            url="https://example.test/tiles/5/13/26.png",
            body_sha256="fake-sha",
        )

    payload = load_or_build_raster_tile_payload(
        "chilai_nanhua_day1",
        "imagery",
        5,
        26,
        13,
        cache_root=tmp_path,
        imagery_source=source,
        allow_remote_fetch=True,
        remote_fetch_timeout_seconds=1.5,
        remote_fetcher=fake_fetcher,
    )
    cached_path = raster_tile_cache_path(
        "chilai_nanhua_day1",
        "imagery",
        5,
        26,
        13,
        cache_root=tmp_path,
    )

    assert payload.source == "remote_fetch_cache_fill"
    assert payload.imagery_source_id == "nlsc_photo2"
    assert payload.media_type == "image/png"
    assert cached_path.read_bytes() == remote_body
    assert payload.headers()["X-Scout-Imagery-Source-Id"] == "nlsc_photo2"
    assert payload.headers()["X-Scout-Imagery-Source-Url-Sha256"]

    cached = load_or_build_raster_tile_payload(
        "chilai_nanhua_day1",
        "imagery",
        5,
        26,
        13,
        cache_root=tmp_path,
        imagery_source=source,
        allow_remote_fetch=False,
    )
    assert cached.source == "local_cache"
    assert cached.body == remote_body


def _quadrant_png() -> bytes:
    from PIL import Image

    image = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    colors = {
        (0, 0, 128, 128): (255, 0, 0, 255),
        (128, 0, 256, 128): (0, 255, 0, 255),
        (0, 128, 128, 256): (0, 0, 255, 255),
        (128, 128, 256, 256): (255, 255, 0, 255),
    }
    for box, color in colors.items():
        patch = Image.new("RGBA", (box[2] - box[0], box[3] - box[1]), color)
        image.paste(patch, box[:2])
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()
    assert cached.headers()["X-Scout-Imagery-Source-Id"] == "nlsc_photo2"


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
