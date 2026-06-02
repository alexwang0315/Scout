from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from admin_basemap_tiles import (
    DEFAULT_ATTRIBUTION as OSM_ATTRIBUTION,
    DEFAULT_CACHE_POLICY as OSM_CACHE_POLICY,
    DEFAULT_OSM_TILE_URL_TEMPLATE as OSM_TILE_URL_TEMPLATE,
)
from admin_local_raster_tiles import LOCAL_RASTER_TILE_URL_TEMPLATE
from admin_tile_proxy import LOCAL_OSM_TILE_URL_TEMPLATE


ORDERING_POLICY = "imagery_bottom_api_top"


@dataclass(frozen=True)
class AdminMapLayerSpec:
    layer_id: str
    label: str
    label_zh: str
    layer_kind: str
    z_index: int
    render_mode: str
    source_kind: str
    default_enabled: bool = True


_LAYER_SPECS: dict[str, AdminMapLayerSpec] = {
    "imagery": AdminMapLayerSpec(
        layer_id="imagery",
        label="Imagery",
        label_zh="影像圖層（最底層）",
        layer_kind="imagery",
        z_index=0,
        render_mode="svg_backdrop",
        source_kind="local_metadata",
    ),
    "osm": AdminMapLayerSpec(
        layer_id="osm",
        label="OSM",
        label_zh="OSM 底圖（OpenStreetMap 開放街圖）",
        layer_kind="basemap",
        z_index=10,
        render_mode="osm_raster_tile",
        source_kind="openstreetmap_tile",
    ),
    "terrain": AdminMapLayerSpec(
        layer_id="terrain",
        label="Terrain",
        label_zh="地形視覺化圖層（DEM/DTM hillshade/tint/slope/contours）",
        layer_kind="terrain",
        z_index=20,
        render_mode="svg_backdrop",
        source_kind="terrain_visualization",
    ),
    "risk-score": AdminMapLayerSpec(
        layer_id="risk-score",
        label="Risk score",
        label_zh="風險分數圖層（Scout Risk Engine 候選分數）",
        layer_kind="evidence",
        z_index=60,
        render_mode="svg_overlay",
        source_kind="scout_risk_engine",
        default_enabled=False,
    ),
    "risk-ribbon": AdminMapLayerSpec(
        layer_id="risk-ribbon",
        label="Risk ribbon",
        label_zh="路徑風險色帶（Route Risk Ribbon，沿路徑分段顯示風險）",
        layer_kind="evidence",
        z_index=61,
        render_mode="svg_overlay",
        source_kind="scout_risk_engine",
    ),
    "risk-heatmap": AdminMapLayerSpec(
        layer_id="risk-heatmap",
        label="Risk heat",
        label_zh="校準熱區圖層（Calibrated Heat Map，本 workspace 相對熱區）",
        layer_kind="evidence",
        z_index=62,
        render_mode="svg_overlay",
        source_kind="scout_risk_engine",
    ),
    "risk-delta": AdminMapLayerSpec(
        layer_id="risk-delta",
        label="Risk delta",
        label_zh="風險差異圖層（Delta，比對 baseline 與 calibrated heat）",
        layer_kind="evidence",
        z_index=63,
        render_mode="svg_overlay",
        source_kind="scout_risk_engine",
        default_enabled=False,
    ),
    "corridors": AdminMapLayerSpec(
        layer_id="corridors",
        label="Corridors",
        label_zh="路廊圖層（可通行路徑脈絡）",
        layer_kind="evidence",
        z_index=40,
        render_mode="svg_overlay",
        source_kind="map_context",
    ),
    "hazards": AdminMapLayerSpec(
        layer_id="hazards",
        label="Hazards",
        label_zh="危險地形/風險圖層",
        layer_kind="evidence",
        z_index=76,
        render_mode="svg_overlay",
        source_kind="map_context",
    ),
    "route": AdminMapLayerSpec(
        layer_id="route",
        label="Route",
        label_zh="路線軌跡圖層",
        layer_kind="evidence",
        z_index=50,
        render_mode="svg_overlay",
        source_kind="route_fixture",
    ),
    "reference-tracks": AdminMapLayerSpec(
        layer_id="reference-tracks",
        label="Reference tracks",
        label_zh="參考軌跡圖層（專家/山友 GPX）",
        layer_kind="evidence",
        z_index=52,
        render_mode="svg_overlay",
        source_kind="reference_track",
    ),
    "retreat": AdminMapLayerSpec(
        layer_id="retreat",
        label="Retreat",
        label_zh="撤退/折返路線圖層",
        layer_kind="evidence",
        z_index=54,
        render_mode="svg_overlay",
        source_kind="planning_candidate",
    ),
    "segments": AdminMapLayerSpec(
        layer_id="segments",
        label="Segments",
        label_zh="分段圖層",
        layer_kind="evidence",
        z_index=56,
        render_mode="svg_overlay",
        source_kind="planning_candidate",
    ),
    "checkpoints": AdminMapLayerSpec(
        layer_id="checkpoints",
        label="Checkpoints",
        label_zh="CP 檢查點圖層",
        layer_kind="evidence",
        z_index=72,
        render_mode="svg_overlay",
        source_kind="planning_candidate",
    ),
    "pois": AdminMapLayerSpec(
        layer_id="pois",
        label="POI",
        label_zh="POI 興趣點/關鍵地點圖層",
        layer_kind="evidence",
        z_index=74,
        render_mode="svg_overlay",
        source_kind="map_context",
    ),
    "route-notes": AdminMapLayerSpec(
        layer_id="route-notes",
        label="Route notes",
        label_zh="山友註記/路況經驗圖層",
        layer_kind="evidence",
        z_index=80,
        render_mode="svg_overlay",
        source_kind="route_note_candidate",
    ),
    "mcp": AdminMapLayerSpec(
        layer_id="mcp",
        label="MCP",
        label_zh="MCP 主要關鍵點圖層",
        layer_kind="evidence",
        z_index=82,
        render_mode="svg_overlay",
        source_kind="major_critical_point_candidate",
    ),
    "events": AdminMapLayerSpec(
        layer_id="events",
        label="Ln events",
        label_zh="Ln 安全事件圖層",
        layer_kind="evidence",
        z_index=85,
        render_mode="svg_overlay",
        source_kind="runtime_evidence",
    ),
    "weather-api": AdminMapLayerSpec(
        layer_id="weather-api",
        label="Weather API",
        label_zh="氣象 API 圖層（最上層）",
        layer_kind="api",
        z_index=100,
        render_mode="api_overlay",
        source_kind="weather_api_reference",
    ),
}


def build_pretrip_map_layers(
    *,
    source_refs: Mapping[str, str],
    weather: Mapping[str, Any],
) -> list[dict[str, Any]]:
    risk_delta_source = source_refs.get("risk_delta") or _paired_source_ref(
        source_refs.get("risk_ribbon"),
        source_refs.get("calibrated_risk_heatmap"),
    )
    sources = {
        "imagery": (
            "pretrip.map_layer.imagery",
            source_refs.get("imagery") or source_refs.get("map_context"),
        ),
        "osm": ("pretrip.map_layer.osm", source_refs.get("map_context")),
        "terrain": (
            "pretrip.map_layer.terrain",
            source_refs.get("terrain_visualization") or source_refs.get("segment_dtm"),
        ),
        "risk-score": (
            "pretrip.map_layer.risk_score",
            source_refs.get("risk_score_points")
            or source_refs.get("risk_score_points_metadata"),
        ),
        "risk-ribbon": (
            "pretrip.map_layer.risk_ribbon",
            source_refs.get("risk_ribbon")
            or source_refs.get("risk_ribbon_metadata"),
        ),
        "risk-heatmap": (
            "pretrip.map_layer.risk_heatmap",
            source_refs.get("calibrated_risk_heatmap")
            or source_refs.get("calibrated_risk_heatmap_metadata"),
        ),
        "risk-delta": (
            "pretrip.map_layer.risk_delta",
            risk_delta_source,
        ),
        "corridors": ("pretrip.map_layer.corridors", source_refs.get("map_candidates")),
        "hazards": ("pretrip.map_layer.hazards", source_refs.get("map_candidates")),
        "route": ("pretrip.map_layer.route", source_refs.get("route_summary")),
        "reference-tracks": (
            "pretrip.map_layer.reference_tracks",
            source_refs.get("reference_track_display_geometry")
            or source_refs.get("reference_tracks"),
        ),
        "retreat": ("pretrip.map_layer.retreat", source_refs.get("retreat_routes")),
        "segments": ("pretrip.map_layer.segments", source_refs.get("segments")),
        "checkpoints": ("pretrip.map_layer.checkpoints", source_refs.get("checkpoints")),
        "pois": ("pretrip.map_layer.pois", source_refs.get("map_candidates")),
        "route-notes": ("pretrip.map_layer.route_notes", source_refs.get("route_notes")),
        "mcp": ("pretrip.map_layer.mcp", source_refs.get("mcp_candidates")),
        "weather-api": (
            str(weather.get("source_id") or "pretrip.map_layer.weather_api"),
            str(weather.get("source_path") or source_refs.get("weather_daylight") or ""),
        ),
    }
    layer_order = [
            "imagery",
            "osm",
            "terrain",
        ]
    layer_order.extend(
        [
            "corridors",
            "route",
            "reference-tracks",
            "retreat",
            "segments",
        ]
    )
    if sources["risk-score"][1]:
        layer_order.append("risk-score")
    if sources["risk-ribbon"][1]:
        layer_order.append("risk-ribbon")
    if sources["risk-heatmap"][1]:
        layer_order.append("risk-heatmap")
    if sources["risk-delta"][1]:
        layer_order.append("risk-delta")
    layer_order.extend(
        [
            "checkpoints",
            "pois",
            "hazards",
            "route-notes",
            "mcp",
            "weather-api",
        ]
    )
    return _build_layers(
        tuple(layer_order),
        sources=sources,
        external_api_calls_made={
            "weather-api": bool(weather.get("external_api_calls_made")),
        },
    )


def build_after_action_map_layers(
    *,
    map_source_path: str,
    map_metadata: Mapping[str, Any],
    route_source_path: str | None = None,
    mission_graph_source_path: str | None = None,
    incident_store_path: str | None = None,
    risk_score_source_path: str | None = None,
    risk_ribbon_source_path: str | None = None,
    risk_heatmap_source_path: str | None = None,
    risk_delta_source_path: str | None = None,
) -> list[dict[str, Any]]:
    resolved_risk_delta_source = risk_delta_source_path or _paired_source_ref(
        risk_ribbon_source_path,
        risk_heatmap_source_path,
    )
    map_source = str(map_metadata.get("source") or "map_context")
    sources = {
        "imagery": ("after_action.map_layer.imagery", map_source_path),
        "osm": ("after_action.map_layer.osm", map_source_path),
        "risk-score": ("after_action.map_layer.risk_score", risk_score_source_path),
        "risk-ribbon": ("after_action.map_layer.risk_ribbon", risk_ribbon_source_path),
        "risk-heatmap": ("after_action.map_layer.risk_heatmap", risk_heatmap_source_path),
        "risk-delta": ("after_action.map_layer.risk_delta", resolved_risk_delta_source),
        "corridors": ("after_action.map_layer.corridors", map_source_path),
        "hazards": ("after_action.map_layer.hazards", map_source_path),
        "route": ("after_action.map_layer.route", route_source_path),
        "checkpoints": ("after_action.map_layer.checkpoints", mission_graph_source_path),
        "events": ("after_action.map_layer.events", incident_store_path),
        "weather-api": ("after_action.map_layer.weather_api", None),
    }
    layer_order = ["imagery", "osm"]
    if risk_score_source_path:
        layer_order.append("risk-score")
    layer_order.extend(["corridors", "route"])
    if risk_ribbon_source_path:
        layer_order.append("risk-ribbon")
    if risk_heatmap_source_path:
        layer_order.append("risk-heatmap")
    if resolved_risk_delta_source:
        layer_order.append("risk-delta")
    layer_order.extend(["checkpoints", "hazards", "events", "weather-api"])
    layers = _build_layers(
        tuple(layer_order),
        sources=sources,
        available={
            "risk-score": bool(risk_score_source_path),
            "risk-ribbon": bool(risk_ribbon_source_path),
            "risk-heatmap": bool(risk_heatmap_source_path),
            "risk-delta": bool(resolved_risk_delta_source),
            "weather-api": False,
        },
        default_enabled={
            "risk-score": False,
            "risk-delta": False,
            "weather-api": False,
        },
    )
    return [
        {
            **layer,
            "source_context_kind": map_source
            if layer["layer_id"] == "osm"
            else layer["source_kind"],
        }
        for layer in layers
    ]


def map_layer_ids(layers: list[dict[str, Any]]) -> list[str]:
    return [str(layer["layer_id"]) for layer in layers]


def _paired_source_ref(first: str | None, second: str | None) -> str | None:
    if first and second:
        return f"{first} + {second}"
    return None


def _build_layers(
    layer_ids: tuple[str, ...],
    *,
    sources: Mapping[str, tuple[str, str | None]],
    available: Mapping[str, bool] | None = None,
    default_enabled: Mapping[str, bool] | None = None,
    external_api_calls_made: Mapping[str, bool] | None = None,
) -> list[dict[str, Any]]:
    availability = available or {}
    defaults = default_enabled or {}
    external_api = external_api_calls_made or {}
    layers = [
        _layer_dict(
            _LAYER_SPECS[layer_id],
            source_id=sources.get(layer_id, (f"map_layer.{layer_id}", None))[0],
            source_path=sources.get(layer_id, (f"map_layer.{layer_id}", None))[1],
            available=availability.get(layer_id, True),
            default_enabled=defaults.get(
                layer_id,
                _LAYER_SPECS[layer_id].default_enabled,
            ),
            external_api_calls_made=external_api.get(layer_id, False),
        )
        for layer_id in layer_ids
    ]
    return sorted(layers, key=lambda layer: int(layer["z_index"]))


def _layer_dict(
    spec: AdminMapLayerSpec,
    *,
    source_id: str,
    source_path: str | None,
    available: bool,
    default_enabled: bool,
    external_api_calls_made: bool,
) -> dict[str, Any]:
    return {
        "layer_id": spec.layer_id,
        "data_layer_group": spec.layer_id,
        "label": spec.label,
        "label_zh": spec.label_zh,
        "layer_kind": spec.layer_kind,
        "z_index": spec.z_index,
        "render_mode": spec.render_mode,
        "source_kind": spec.source_kind,
        "source_id": source_id,
        "source_path": source_path,
        "available": available,
        "default_enabled": default_enabled,
        "toggleable": True,
        "external_api_calls_made": external_api_calls_made,
        "ordering_policy": ORDERING_POLICY,
        **_layer_renderer_contract(spec.layer_id),
    }


def _layer_renderer_contract(layer_id: str) -> dict[str, Any]:
    if layer_id == "imagery":
        return {
            "local_raster_manifest_supported": True,
            "preferred_manifest_kind": "admin_local_raster_source_manifest",
            "local_raster_tile_url_template": LOCAL_RASTER_TILE_URL_TEMPLATE,
            "local_raster_tile_cache_policy": (
                "local_file_cache_then_transparent_fallback"
            ),
            "external_network_required": False,
            "tile_cutting_required": False,
            "downloads_tiles_into_repo": False,
        }
    if layer_id == "osm":
        return {
            "tile_url_template": OSM_TILE_URL_TEMPLATE,
            "local_proxy_tile_url_template": LOCAL_OSM_TILE_URL_TEMPLATE,
            "attribution": OSM_ATTRIBUTION,
            "external_network_required": True,
            "local_proxy_external_network_required": False,
            "cache_policy": OSM_CACHE_POLICY,
            "local_proxy_cache_policy": "local_file_cache_then_offline_fallback",
            "downloads_tiles_into_repo": False,
        }
    if layer_id == "terrain":
        return {
            "terrain_visualization_modes": [
                "hillshade",
                "elevation_tint",
                "slope_shading",
                "contours",
            ],
            "terrain_visualization_ref_key": "terrain_visualization_ref",
            "terrain_visualization_layer": True,
            "risk_heat_layer": False,
            "slope_class_breaks": [
                {
                    "class_id": "slope-0-10",
                    "label": "0-10 deg",
                    "color": "#b7e4a8",
                },
                {
                    "class_id": "slope-10-20",
                    "label": "10-20 deg",
                    "color": "#d9ef8b",
                },
                {
                    "class_id": "slope-20-30",
                    "label": "20-30 deg",
                    "color": "#fee08b",
                },
                {
                    "class_id": "slope-30-40",
                    "label": "30-40 deg",
                    "color": "#fdae61",
                },
                {
                    "class_id": "slope-40-50",
                    "label": "40-50 deg",
                    "color": "#f46d43",
                },
                {
                    "class_id": "slope-gt-50",
                    "label": ">50 deg",
                    "color": "#d73027",
                },
            ],
            "contour_interval_m": 100.0,
            "runtime_safety_truth": False,
        }
    if layer_id == "weather-api":
        return {
            "overlay_endpoint_template": (
                "/admin/pretrip/projects/{project_id}/weather-overlay"
            ),
            "overlay_render_mode": "svg_badges_and_summary_panel",
            "external_network_required": False,
            "secret_value_embedded": False,
        }
    return {}
