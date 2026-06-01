import hashlib
from pathlib import Path

import pytest

from admin_tile_proxy import (
    LOCAL_OSM_TILE_URL_TEMPLATE,
    build_osm_tile_proxy_contract,
    load_or_build_osm_tile_payload,
    osm_tile_cache_path,
    validate_osm_tile_coords,
)


def test_osm_tile_proxy_contract_is_local_cache_only(tmp_path):
    contract = build_osm_tile_proxy_contract(cache_root=tmp_path)

    assert contract["artifact_kind"] == "admin_osm_tile_proxy_contract"
    assert contract["status"] == "local_proxy_ready"
    assert contract["url_template"] == LOCAL_OSM_TILE_URL_TEMPLATE
    assert contract["cache_root"] == str(tmp_path)
    assert contract["cache_policy"] == "local_file_cache_then_offline_fallback"
    assert contract["external_network_fetch_allowed"] is False
    assert contract["downloads_tiles_into_repo"] is False


def test_osm_tile_proxy_serves_generated_offline_fallback_without_cache(tmp_path):
    payload = load_or_build_osm_tile_payload(1, 1, 1, cache_root=tmp_path)

    assert payload.media_type == "image/svg+xml"
    assert payload.source == "offline_fallback"
    assert payload.cache_path == tmp_path / "1" / "1" / "1.png"
    assert b"OSM offline 1/1/1" in payload.body
    assert payload.body_sha256 == hashlib.sha256(payload.body).hexdigest()
    assert payload.headers()["X-Scout-Tile-Source"] == "offline_fallback"
    assert payload.headers()["Cache-Control"] == "no-store"


def test_osm_tile_proxy_can_serve_transparent_ui_fallback_without_cache(tmp_path):
    payload = load_or_build_osm_tile_payload(
        1,
        1,
        1,
        cache_root=tmp_path,
        fallback_style="transparent",
    )

    assert payload.media_type == "image/png"
    assert payload.source == "transparent_fallback"
    assert payload.cache_path == tmp_path / "1" / "1" / "1.png"
    assert b"OSM offline" not in payload.body
    assert payload.body.startswith(b"\x89PNG\r\n\x1a\n")
    assert payload.headers()["Cache-Control"] == "no-store"


def test_osm_tile_proxy_serves_cached_png_when_present(tmp_path):
    cached_path = tmp_path / "2" / "3" / "1.png"
    cached_path.parent.mkdir(parents=True)
    cached_path.write_bytes(b"\x89PNG\r\n\x1a\ncached-demo-tile")

    payload = load_or_build_osm_tile_payload(2, 3, 1, cache_root=tmp_path)

    assert payload.media_type == "image/png"
    assert payload.source == "local_cache"
    assert payload.cache_path == cached_path
    assert payload.body == cached_path.read_bytes()
    assert payload.headers()["Cache-Control"] == "no-cache, max-age=0, must-revalidate"


def test_osm_tile_proxy_rejects_invalid_coordinates_and_missing_cache(tmp_path):
    assert validate_osm_tile_coords(20, 0, 0) == {"z": 20, "x": 0, "y": 0}
    with pytest.raises(ValueError):
        validate_osm_tile_coords(21, 0, 0)
    with pytest.raises(ValueError):
        validate_osm_tile_coords(1, 3, 0)

    with pytest.raises(FileNotFoundError):
        load_or_build_osm_tile_payload(
            1,
            1,
            1,
            cache_root=tmp_path,
            fallback_enabled=False,
        )

    assert osm_tile_cache_path("1", "1", "1", cache_root=tmp_path) == Path(
        tmp_path / "1" / "1" / "1.png"
    )
