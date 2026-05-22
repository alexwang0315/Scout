from admin_map_layers import (
    build_after_action_map_layers,
    build_pretrip_map_layers,
    map_layer_ids,
)


def test_pretrip_map_layers_order_imagery_bottom_and_api_top():
    layers = build_pretrip_map_layers(
        source_refs={
            "imagery": "external/local/chilai_nanhua_day1.local_raster_source_manifest.json",
            "map_context": "normalized/map/map_context.geojson",
            "map_candidates": "candidates/map_candidates.json",
            "route_summary": "normalized/route_summary.json",
            "segment_dtm": "normalized/terrain/segment_dtm_coverage.json",
            "weather_daylight": "outputs/weather_daylight_evidence.json",
        },
        weather={
            "source_id": "weather_daylight.chilai_nanhua_day1",
            "source_path": "outputs/weather_daylight_evidence.json",
            "external_api_calls_made": False,
            "status": "fixture_backed",
        },
    )

    assert map_layer_ids(layers) == [
        "imagery",
        "osm",
        "terrain",
        "corridors",
        "hazards",
        "route",
        "reference-tracks",
        "retreat",
        "segments",
        "checkpoints",
        "pois",
        "route-notes",
        "weather-api",
    ]
    assert [layer["z_index"] for layer in layers] == sorted(
        layer["z_index"] for layer in layers
    )
    assert layers[0]["layer_kind"] == "imagery"
    assert layers[0]["label_zh"].startswith("影像圖層")
    assert layers[0]["source_path"] == (
        "external/local/chilai_nanhua_day1.local_raster_source_manifest.json"
    )
    assert layers[0]["local_raster_manifest_supported"] is True
    assert layers[0]["preferred_manifest_kind"] == (
        "admin_local_raster_source_manifest"
    )
    assert layers[0]["local_raster_tile_url_template"] == (
        "/admin/tiles/imagery/{project_id}/{layer_id}/{z}/{x}/{y}.png"
    )
    assert layers[0]["local_raster_tile_cache_policy"] == (
        "local_file_cache_then_transparent_fallback"
    )
    assert layers[0]["external_network_required"] is False
    assert layers[0]["tile_cutting_required"] is False
    assert layers[0]["downloads_tiles_into_repo"] is False
    assert layers[1]["render_mode"] == "osm_raster_tile"
    assert layers[1]["source_kind"] == "openstreetmap_tile"
    assert layers[1]["tile_url_template"] == (
        "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
    )
    assert layers[1]["external_network_required"] is True
    assert layers[1]["local_proxy_tile_url_template"] == (
        "/admin/tiles/osm/{z}/{x}/{y}.png"
    )
    assert layers[1]["local_proxy_external_network_required"] is False
    assert layers[1]["cache_policy"] == "browser_http_cache_or_local_proxy"
    assert layers[1]["local_proxy_cache_policy"] == (
        "local_file_cache_then_offline_fallback"
    )
    assert layers[1]["downloads_tiles_into_repo"] is False
    assert layers[-1]["layer_kind"] == "api"
    assert layers[-1]["label_zh"].startswith("氣象 API")
    assert layers[-1]["render_mode"] == "api_overlay"
    assert layers[-1]["overlay_endpoint_template"] == (
        "/admin/pretrip/projects/{project_id}/weather-overlay"
    )
    assert layers[-1]["overlay_render_mode"] == "svg_badges_and_summary_panel"
    assert layers[-1]["secret_value_embedded"] is False
    assert layers[-1]["external_api_calls_made"] is False
    assert all(layer["toggleable"] is True for layer in layers)


def test_after_action_map_layers_reuse_the_same_base_and_api_order():
    layers = build_after_action_map_layers(
        map_source_path="tests/fixtures/maps/scout_260512_overpass_map_context.geojson",
        map_metadata={
            "source": "openstreetmap_overpass",
            "confidence": 0.72,
            "known_staleness_risk": "medium",
        },
    )

    assert map_layer_ids(layers) == [
        "imagery",
        "osm",
        "corridors",
        "hazards",
        "route",
        "checkpoints",
        "events",
        "weather-api",
    ]
    assert [layer["z_index"] for layer in layers] == sorted(
        layer["z_index"] for layer in layers
    )
    assert layers[0]["layer_id"] == "imagery"
    assert layers[1]["layer_id"] == "osm"
    assert layers[1]["source_kind"] == "openstreetmap_tile"
    assert layers[1]["tile_url_template"] == (
        "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
    )
    assert layers[1]["external_network_required"] is True
    assert layers[1]["local_proxy_tile_url_template"] == (
        "/admin/tiles/osm/{z}/{x}/{y}.png"
    )
    assert layers[1]["local_proxy_external_network_required"] is False
    assert layers[-1]["layer_id"] == "weather-api"
    assert layers[-1]["available"] is False
    assert layers[-1]["default_enabled"] is False
    assert layers[-1]["render_mode"] == "api_overlay"
    assert layers[-1]["external_network_required"] is False
    assert layers[-1]["external_api_calls_made"] is False
