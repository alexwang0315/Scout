import re
from pathlib import Path

from admin_map_layers import (
    build_after_action_map_layers,
    build_pretrip_map_layers,
    map_layer_ids,
)


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_ALPHA_WORKSPACE_LAYER_CONTROLS = [
    "imagery",
    "rudy",
    "rudy-twmap",
    "relief",
    "geology",
    "topo-5k",
    "forest",
    "osm",
    "terrain",
    "risk-score",
    "risk-ribbon",
    "risk-heatmap",
    "risk-delta",
    "cwa-qpf",
    "soil-moisture",
    "antecedent-rain",
    "cwa-weather",
    "corridors",
    "overpass",
    "route",
    "reference-tracks",
    "retreat",
    "segments",
    "checkpoints",
    "pois",
    "hazards",
    "mcp",
    "boss-points",
    "route-notes",
    "events",
    "weather-api",
]


def test_pretrip_map_layers_order_imagery_bottom_and_api_top():
    layers = build_pretrip_map_layers(
        source_refs={
            "imagery": "external/local/chilai_nanhua_day1.local_raster_source_manifest.json",
            "map_context": "normalized/map/map_context.geojson",
            "map_candidates": "candidates/map_candidates.json",
            "route_summary": "normalized/route_summary.json",
            "segment_dtm": "normalized/terrain/segment_dtm_coverage.json",
            "overpass_evidence": "outputs/layers/normalized/overpass_vector_evidence.geojson",
            "risk_score_points": "outputs/risk_score_points.geojson",
            "risk_ribbon": "outputs/risk_ribbon.geojson",
            "calibrated_risk_heatmap": "outputs/risk_heatmap.geojson",
            "soil_moisture": "outputs/environment/gee/soil_moisture_grid.geojson",
            "antecedent_rain": "outputs/environment/gee/antecedent_rain_grid.geojson",
            "cwa_qpf_grid": "outputs/environment/cwa/qpf_grid.geojson",
            "route_weather_package": "outputs/route_weather_package.json",
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
        "rudy",
        "rudy-twmap",
        "relief",
        "geology",
        "topo-5k",
        "forest",
        "osm",
        "terrain",
        "corridors",
        "overpass",
        "route",
        "reference-tracks",
        "retreat",
        "segments",
        "risk-ribbon",
        "risk-heatmap",
        "risk-delta",
        "soil-moisture",
        "antecedent-rain",
        "cwa-qpf",
        "risk-score",
        "checkpoints",
        "pois",
        "hazards",
        "route-notes",
        "cwa-weather",
        "mcp",
        "boss-points",
        "events",
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
    assert layers[0]["render_mode"] == "wmts_raster_tile"
    assert layers[0]["source_kind"] == "wmts_tile"
    assert layers[0]["local_raster_manifest_supported"] is False
    assert layers[0]["preferred_manifest_kind"] == "scout_imagery_source_registry"
    assert layers[0]["raster_tile_delivery"] == "direct_wmts_runtime"
    assert layers[0]["local_raster_tile_cache_policy"] == "disabled_use_wmts_runtime"
    assert layers[0]["external_network_required"] is True
    assert layers[0]["scout_imagery_source_registry_supported"] is True
    assert layers[0]["imagery_source_id"] == "nlsc_photo2"
    assert layers[0]["default_imagery_source_id"] == "nlsc_photo2"
    assert layers[0]["remote_fetch_requires_explicit_enable"] is False
    assert layers[0]["tile_cutting_required"] is False
    assert layers[0]["downloads_tiles_into_repo"] is False
    osm = next(layer for layer in layers if layer["layer_id"] == "osm")
    assert osm["render_mode"] == "osm_raster_tile"
    assert osm["source_kind"] == "openstreetmap_tile"
    assert osm["tile_url_template"] == (
        "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
    )
    assert osm["external_network_required"] is True
    assert osm["local_proxy_tile_url_template"] == (
        "/admin/tiles/osm/{z}/{x}/{y}.png"
    )
    assert osm["local_proxy_external_network_required"] is False
    assert osm["cache_policy"] == "browser_http_cache_or_local_proxy"
    assert osm["local_proxy_cache_policy"] == (
        "local_file_cache_then_offline_fallback"
    )
    assert osm["downloads_tiles_into_repo"] is False
    terrain = next(layer for layer in layers if layer["layer_id"] == "terrain")
    assert terrain["source_kind"] == "terrain_visualization"
    assert terrain["terrain_visualization_layer"] is True
    assert terrain["risk_heat_layer"] is False
    assert [item["class_id"] for item in terrain["slope_class_breaks"]] == [
        "slope-0-10",
        "slope-10-20",
        "slope-20-30",
        "slope-30-40",
        "slope-40-50",
        "slope-gt-50",
    ]
    overpass = next(layer for layer in layers if layer["layer_id"] == "overpass")
    assert overpass["source_kind"] == "overpass_vector_evidence"
    assert overpass["available"] is True
    assert overpass["default_enabled"] is False
    events = next(layer for layer in layers if layer["layer_id"] == "events")
    assert events["available"] is False
    cwa_qpf = next(layer for layer in layers if layer["layer_id"] == "cwa-qpf")
    assert cwa_qpf["provider"] == "cwa_opendata"
    assert cwa_qpf["geojson_ref_key"] == "cwa_qpf_grid_ref"
    assert cwa_qpf["runtime_safety_truth"] is False
    soil = next(layer for layer in layers if layer["layer_id"] == "soil-moisture")
    assert soil["provider"] == "google_earth_engine"
    assert soil["dataset_family"] == "SMAP"
    rain = next(layer for layer in layers if layer["layer_id"] == "antecedent-rain")
    assert rain["dataset_family"] == "GPM_IMERG"
    cwa_weather = next(layer for layer in layers if layer["layer_id"] == "cwa-weather")
    assert cwa_weather["source_kind"] == "cwa_weather_candidate"
    assert cwa_weather["secret_value_embedded"] is False
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


def test_admin_pages_expose_the_same_alpha_workspace_layer_controls():
    pages = [
        ROOT / "docs" / "admin" / "phase4-pretrip-planning.html",
        ROOT / "docs" / "admin" / "phase-3-5-runtime-debug.html",
        ROOT / "docs" / "admin" / "phase1-after-action.html",
    ]

    for page in pages:
        html = page.read_text(encoding="utf-8")
        static_layer_controls = [
            layer
            for layer in re.findall(r'data-layer="([^"]+)"', html)
            if not layer.startswith("${")
        ]
        expected_controls = list(EXPECTED_ALPHA_WORKSPACE_LAYER_CONTROLS)
        if page.name == "phase1-after-action.html":
            expected_controls.insert(
                expected_controls.index("reference-tracks"),
                "completed-track",
            )
        assert static_layer_controls == expected_controls


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
        "rudy",
        "rudy-twmap",
        "relief",
        "geology",
        "topo-5k",
        "forest",
        "osm",
        "terrain",
        "corridors",
        "overpass",
        "route",
        "completed-track",
        "reference-tracks",
        "retreat",
        "segments",
        "risk-ribbon",
        "risk-heatmap",
        "risk-delta",
        "soil-moisture",
        "antecedent-rain",
        "cwa-qpf",
        "risk-score",
        "checkpoints",
        "pois",
        "hazards",
        "route-notes",
        "cwa-weather",
        "mcp",
        "boss-points",
        "events",
        "weather-api",
    ]
    assert [layer["z_index"] for layer in layers] == sorted(
        layer["z_index"] for layer in layers
    )
    assert layers[0]["layer_id"] == "imagery"
    osm = next(layer for layer in layers if layer["layer_id"] == "osm")
    assert osm["source_kind"] == "openstreetmap_tile"
    assert osm["tile_url_template"] == (
        "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
    )
    assert osm["external_network_required"] is True
    assert osm["local_proxy_tile_url_template"] == (
        "/admin/tiles/osm/{z}/{x}/{y}.png"
    )
    assert osm["local_proxy_external_network_required"] is False
    terrain = next(layer for layer in layers if layer["layer_id"] == "terrain")
    assert terrain["available"] is False
    overpass = next(layer for layer in layers if layer["layer_id"] == "overpass")
    assert overpass["source_kind"] == "overpass_vector_evidence"
    assert overpass["available"] is True
    assert overpass["default_enabled"] is False
    reference_tracks = next(layer for layer in layers if layer["layer_id"] == "reference-tracks")
    assert reference_tracks["available"] is False
    assert layers[-1]["layer_id"] == "weather-api"
    assert layers[-1]["available"] is False
    assert layers[-1]["default_enabled"] is False
    assert layers[-1]["render_mode"] == "api_overlay"
    assert layers[-1]["external_network_required"] is False
    assert layers[-1]["external_api_calls_made"] is False
