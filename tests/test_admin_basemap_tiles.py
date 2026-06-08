from __future__ import annotations

from pathlib import Path

import admin_basemap_tiles as basemap


def test_normalize_bbox_accepts_south_west_north_east_shape():
    normalized = basemap.normalize_bbox_wgs84(
        {
            "north": 24.142,
            "south": 24.101,
            "east": 121.356,
            "west": 121.301,
        }
    )

    assert normalized == {
        "south": 24.101,
        "west": 121.301,
        "north": 24.142,
        "east": 121.356,
    }


def test_normalize_bbox_accepts_min_max_shape_and_orders_values():
    normalized = basemap.normalize_bbox_wgs84(
        {
            "min_lat": 24.142,
            "min_lon": 121.356,
            "max_lat": 24.101,
            "max_lon": 121.301,
        }
    )

    assert normalized == {
        "south": 24.101,
        "west": 121.301,
        "north": 24.142,
        "east": 121.356,
    }


def test_chilai_like_bbox_generates_bounded_tile_list():
    contract = basemap.build_osm_basemap_contract(
        {
            "min_lat": 23.964,
            "min_lon": 121.255,
            "max_lat": 24.045,
            "max_lon": 121.355,
        },
        max_tiles=8,
    )

    tiles = contract["tiles"]

    assert tiles
    assert len(tiles) <= 8
    assert contract["tile_count"] == len(tiles)
    assert contract["zoom"] <= basemap.DEFAULT_MOUNTAIN_ROUTE_ZOOM
    assert all(tile["source_kind"] == "openstreetmap_tile" for tile in tiles)
    assert all(tile["external_network_required"] is True for tile in tiles)
    assert all(tile["cache_policy"] == basemap.DEFAULT_CACHE_POLICY for tile in tiles)


def test_default_chilai_like_bbox_prefers_crisp_demo_zoom_under_tile_cap():
    contract = basemap.build_osm_basemap_contract(
        {
            "min_lat": 24.043338071400207,
            "min_lon": 121.21036249036372,
            "max_lat": 24.057907788530006,
            "max_lon": 121.28079717511966,
        },
    )

    assert contract["zoom"] >= 16
    assert 16 < contract["tile_count"] <= basemap.DEFAULT_MAX_TILES


def test_default_openstreetmap_url_and_custom_template():
    default_contract = basemap.build_osm_basemap_contract(
        {"south": 24.1, "west": 121.3, "north": 24.12, "east": 121.32},
        zoom=13,
    )
    default_tile = default_contract["tiles"][0]

    assert default_tile["url"] == (
        f"https://tile.openstreetmap.org/{default_tile['z']}/"
        f"{default_tile['x']}/{default_tile['y']}.png"
    )
    assert default_tile["tile_url_template"] == basemap.DEFAULT_OSM_TILE_URL_TEMPLATE
    assert "OpenStreetMap" in default_tile["attribution"]

    custom_contract = basemap.build_osm_basemap_contract(
        {"south": 24.1, "west": 121.3, "north": 24.12, "east": 121.32},
        zoom=13,
        tile_url_template="https://tiles.example.test/{z}/{x}/{y}.webp",
    )
    custom_tile = custom_contract["tiles"][0]

    assert custom_tile["url"] == (
        f"https://tiles.example.test/{custom_tile['z']}/"
        f"{custom_tile['x']}/{custom_tile['y']}.webp"
    )
    assert custom_tile["tile_url_template"] == "https://tiles.example.test/{z}/{x}/{y}.webp"


def test_svg_image_specs_are_ready_for_normalized_viewport_append():
    contract = basemap.build_osm_basemap_contract(
        {"south": 24.1, "west": 121.3, "north": 24.12, "east": 121.32},
        zoom=13,
    )

    images = contract["svg_images"]

    assert images
    assert len(images) == contract["tile_count"]
    for image in images:
        assert image["tag"] == "image"
        assert image["href"].startswith("https://tile.openstreetmap.org/")
        assert {"x", "y", "width", "height", "href", "opacity"}.issubset(image)
        assert -400 <= image["x"] <= basemap.DEFAULT_VIEWPORT_WIDTH + 400
        assert -400 <= image["y"] <= basemap.DEFAULT_VIEWPORT_HEIGHT + 400
        max_nearby_tile_size = max(
            basemap.DEFAULT_VIEWPORT_WIDTH,
            basemap.DEFAULT_VIEWPORT_HEIGHT,
        ) * 1.5
        assert 0 < image["width"] <= max_nearby_tile_size
        assert 0 < image["height"] <= max_nearby_tile_size
        assert image["data-source-kind"] == "openstreetmap_tile"
        assert image["data-tile-z"] == str(contract["zoom"])


def test_source_boundary_has_no_network_client_imports():
    source = Path(basemap.__file__).read_text()

    forbidden_fragments = [
        "import requests",
        "from requests",
        "import httpx",
        "from httpx",
        "import fastapi",
        "from fastapi",
    ]
    assert not any(fragment in source for fragment in forbidden_fragments)
