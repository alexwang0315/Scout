from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from admin_basemap_tiles import (
    DEFAULT_ATTRIBUTION as OSM_ATTRIBUTION,
    DEFAULT_CACHE_POLICY as OSM_CACHE_POLICY,
    DEFAULT_OSM_TILE_URL_TEMPLATE as OSM_TILE_URL_TEMPLATE,
)
from admin_imagery_sources import DEFAULT_IMAGERY_SOURCE_ID, DEFAULT_REGISTRY_ID
from admin_tile_proxy import LOCAL_OSM_TILE_URL_TEMPLATE
from scout_layer_contract import (
    ORDERING_POLICY,
    SCOUT_LAYER_IDS,
    SCOUT_LAYER_RANKS,
    SCOUT_SURFACE_LAYER_IDS,
)


RASTER_OVERLAY_SOURCE_IDS = {
    "imagery": DEFAULT_IMAGERY_SOURCE_ID,
    "rudy": "happyman_rudy",
    "rudy-twmap": "happyman_rudy_twmap",
    "relief": "happyman_colorrelief",
    "geology": "happyman_geo2016",
    "topo-5k": "happyman_tw5k2000",
    "forest": "happyman_forest",
}
WORKSPACE_LAYER_CONTROL_IDS = SCOUT_LAYER_IDS
PRETRIP_LAYER_CONTROL_IDS = SCOUT_SURFACE_LAYER_IDS["pretrip"]
AFTER_ACTION_LAYER_CONTROL_IDS = SCOUT_SURFACE_LAYER_IDS["after-action"]


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
        label_zh="影像圖層（WMTS，最底層）",
        layer_kind="imagery",
        z_index=0,
        render_mode="wmts_raster_tile",
        source_kind="wmts_tile",
    ),
    "rudy": AdminMapLayerSpec(
        layer_id="rudy",
        label="Rudy",
        label_zh="魯地圖圖層（Rudy Map，登山地形底圖）",
        layer_kind="imagery",
        z_index=SCOUT_LAYER_RANKS["rudy"],
        render_mode="wmts_raster_tile",
        source_kind="wmts_kvp_tile",
        default_enabled=False,
    ),
    "rudy-twmap": AdminMapLayerSpec(
        layer_id="rudy-twmap",
        label="Rudy+TW",
        label_zh="魯地圖加 TWMap 樣式圖層（Rudy Map + TWMap）",
        layer_kind="imagery",
        z_index=SCOUT_LAYER_RANKS["rudy-twmap"],
        render_mode="wmts_raster_tile",
        source_kind="wmts_kvp_tile",
        default_enabled=False,
    ),
    "relief": AdminMapLayerSpec(
        layer_id="relief",
        label="Relief",
        label_zh="彩色地形陰影圖層（color relief terrain shading）",
        layer_kind="terrain",
        z_index=SCOUT_LAYER_RANKS["relief"],
        render_mode="wmts_raster_tile",
        source_kind="wmts_kvp_tile",
        default_enabled=False,
    ),
    "geology": AdminMapLayerSpec(
        layer_id="geology",
        label="Geology",
        label_zh="地質圖圖層（geology overlay，規劃證據）",
        layer_kind="terrain",
        z_index=SCOUT_LAYER_RANKS["geology"],
        render_mode="wmts_raster_tile",
        source_kind="wmts_kvp_tile",
        default_enabled=False,
    ),
    "topo-5k": AdminMapLayerSpec(
        layer_id="topo-5k",
        label="Topo 5K",
        label_zh="五千分之一地形圖圖層（1/5000 topo map）",
        layer_kind="terrain",
        z_index=SCOUT_LAYER_RANKS["topo-5k"],
        render_mode="wmts_raster_tile",
        source_kind="wmts_kvp_tile",
        default_enabled=False,
    ),
    "forest": AdminMapLayerSpec(
        layer_id="forest",
        label="Forest",
        label_zh="林班界圖層（forest compartment overlay）",
        layer_kind="terrain",
        z_index=SCOUT_LAYER_RANKS["forest"],
        render_mode="wmts_raster_tile",
        source_kind="wmts_kvp_tile",
        default_enabled=False,
    ),
    "osm": AdminMapLayerSpec(
        layer_id="osm",
        label="OSM",
        label_zh="OSM 底圖（OpenStreetMap 開放街圖）",
        layer_kind="basemap",
        z_index=SCOUT_LAYER_RANKS["osm"],
        render_mode="osm_raster_tile",
        source_kind="openstreetmap_tile",
    ),
    "terrain": AdminMapLayerSpec(
        layer_id="terrain",
        label="Terrain",
        label_zh="地形視覺化圖層（DEM/DTM hillshade/tint/slope/contours）",
        layer_kind="terrain",
        z_index=SCOUT_LAYER_RANKS["terrain"],
        render_mode="svg_backdrop",
        source_kind="terrain_visualization",
    ),
    "risk-score": AdminMapLayerSpec(
        layer_id="risk-score",
        label="Risk score",
        label_zh="風險分數圖層（Scout Risk Engine 候選分數）",
        layer_kind="evidence",
        z_index=SCOUT_LAYER_RANKS["risk-score"],
        render_mode="svg_overlay",
        source_kind="scout_risk_engine",
        default_enabled=False,
    ),
    "risk-ribbon": AdminMapLayerSpec(
        layer_id="risk-ribbon",
        label="Risk ribbon",
        label_zh="路徑風險色帶（Route Risk Ribbon，沿路徑分段顯示風險）",
        layer_kind="evidence",
        z_index=SCOUT_LAYER_RANKS["risk-ribbon"],
        render_mode="svg_overlay",
        source_kind="scout_risk_engine",
    ),
    "risk-heatmap": AdminMapLayerSpec(
        layer_id="risk-heatmap",
        label="Risk calibration",
        label_zh="風險校準熱區圖層（Calibrated Heat Map，本 workspace 相對熱區）",
        layer_kind="evidence",
        z_index=SCOUT_LAYER_RANKS["risk-heatmap"],
        render_mode="svg_overlay",
        source_kind="scout_risk_engine",
    ),
    "risk-delta": AdminMapLayerSpec(
        layer_id="risk-delta",
        label="Risk delta",
        label_zh="風險差異圖層（Delta，比對 baseline 與 calibrated heat）",
        layer_kind="evidence",
        z_index=SCOUT_LAYER_RANKS["risk-delta"],
        render_mode="svg_overlay",
        source_kind="scout_risk_engine",
        default_enabled=False,
    ),
    "soil-moisture": AdminMapLayerSpec(
        layer_id="soil-moisture",
        label="Soil moisture",
        label_zh="土壤含水量圖層（SMAP/GEE hydrology context）",
        layer_kind="environment",
        z_index=SCOUT_LAYER_RANKS["soil-moisture"],
        render_mode="svg_overlay",
        source_kind="gee_soil_moisture_candidate",
        default_enabled=False,
    ),
    "antecedent-rain": AdminMapLayerSpec(
        layer_id="antecedent-rain",
        label="Antecedent rain",
        label_zh="前期累積降雨圖層（GPM IMERG hydrology context）",
        layer_kind="environment",
        z_index=SCOUT_LAYER_RANKS["antecedent-rain"],
        render_mode="svg_overlay",
        source_kind="gee_antecedent_rain_candidate",
        default_enabled=False,
    ),
    "cwa-qpf": AdminMapLayerSpec(
        layer_id="cwa-qpf",
        label="CWA QPF",
        label_zh="定量降水預報圖層（CWA QPF，路線 bbox/corridor 降雨格點）",
        layer_kind="environment",
        z_index=SCOUT_LAYER_RANKS["cwa-qpf"],
        render_mode="geojson_overlay",
        source_kind="cwa_qpf_candidate",
        default_enabled=False,
    ),
    "corridors": AdminMapLayerSpec(
        layer_id="corridors",
        label="Corridors",
        label_zh="路廊圖層（可通行路徑脈絡）",
        layer_kind="evidence",
        z_index=SCOUT_LAYER_RANKS["corridors"],
        render_mode="svg_overlay",
        source_kind="map_context",
    ),
    "hazards": AdminMapLayerSpec(
        layer_id="hazards",
        label="Hazards",
        label_zh="危險地形/風險圖層",
        layer_kind="evidence",
        z_index=SCOUT_LAYER_RANKS["hazards"],
        render_mode="svg_overlay",
        source_kind="map_context",
    ),
    "overpass": AdminMapLayerSpec(
        layer_id="overpass",
        label="Overpass",
        label_zh="Overpass 向量證據圖層（OSM corridor/POI/hazard evidence）",
        layer_kind="evidence",
        z_index=SCOUT_LAYER_RANKS["overpass"],
        render_mode="svg_overlay",
        source_kind="overpass_vector_evidence",
        default_enabled=False,
    ),
    "route": AdminMapLayerSpec(
        layer_id="route",
        label="Route",
        label_zh="路線軌跡圖層",
        layer_kind="evidence",
        z_index=SCOUT_LAYER_RANKS["route"],
        render_mode="svg_overlay",
        source_kind="route_fixture",
    ),
    "completed-track": AdminMapLayerSpec(
        layer_id="completed-track",
        label="Completed track",
        label_zh="完成旅程 GPX 圖層（post-analysis only）",
        layer_kind="evidence",
        z_index=SCOUT_LAYER_RANKS["completed-track"],
        render_mode="svg_overlay",
        source_kind="completed_trip_track",
    ),
    "reference-tracks": AdminMapLayerSpec(
        layer_id="reference-tracks",
        label="Reference tracks",
        label_zh="參考軌跡圖層（專家/山友 GPX）",
        layer_kind="evidence",
        z_index=SCOUT_LAYER_RANKS["reference-tracks"],
        render_mode="svg_overlay",
        source_kind="reference_track",
    ),
    "retreat": AdminMapLayerSpec(
        layer_id="retreat",
        label="Retreat",
        label_zh="撤退/折返路線圖層",
        layer_kind="evidence",
        z_index=SCOUT_LAYER_RANKS["retreat"],
        render_mode="svg_overlay",
        source_kind="planning_candidate",
    ),
    "segments": AdminMapLayerSpec(
        layer_id="segments",
        label="Segments",
        label_zh="分段圖層",
        layer_kind="evidence",
        z_index=SCOUT_LAYER_RANKS["segments"],
        render_mode="svg_overlay",
        source_kind="planning_candidate",
    ),
    "checkpoints": AdminMapLayerSpec(
        layer_id="checkpoints",
        label="Checkpoints",
        label_zh="CP 檢查點圖層",
        layer_kind="evidence",
        z_index=SCOUT_LAYER_RANKS["checkpoints"],
        render_mode="svg_overlay",
        source_kind="planning_candidate",
    ),
    "pois": AdminMapLayerSpec(
        layer_id="pois",
        label="POI",
        label_zh="POI 興趣點/關鍵地點圖層",
        layer_kind="evidence",
        z_index=SCOUT_LAYER_RANKS["pois"],
        render_mode="svg_overlay",
        source_kind="map_context",
    ),
    "route-notes": AdminMapLayerSpec(
        layer_id="route-notes",
        label="Route notes",
        label_zh="山友註記/路況經驗圖層",
        layer_kind="evidence",
        z_index=SCOUT_LAYER_RANKS["route-notes"],
        render_mode="svg_overlay",
        source_kind="route_note_candidate",
    ),
    "cwa-weather": AdminMapLayerSpec(
        layer_id="cwa-weather",
        label="CWA weather",
        label_zh="中央氣象署天氣圖層（警特報/觀測/預報，候選證據）",
        layer_kind="environment",
        z_index=SCOUT_LAYER_RANKS["cwa-weather"],
        render_mode="geojson_overlay",
        source_kind="cwa_weather_candidate",
        default_enabled=False,
    ),
    "mcp": AdminMapLayerSpec(
        layer_id="mcp",
        label="MCP",
        label_zh="MCP 主要關鍵點圖層",
        layer_kind="evidence",
        z_index=SCOUT_LAYER_RANKS["mcp"],
        render_mode="svg_overlay",
        source_kind="major_critical_point_candidate",
    ),
    "boss-points": AdminMapLayerSpec(
        layer_id="boss-points",
        label="Boss points",
        label_zh="魔王點 Challenge Fit 圖層",
        layer_kind="evidence",
        z_index=SCOUT_LAYER_RANKS["boss-points"],
        render_mode="svg_overlay",
        source_kind="pretrip_boss_point_challenge_fit",
    ),
    "events": AdminMapLayerSpec(
        layer_id="events",
        label="Ln events",
        label_zh="Ln 安全事件圖層",
        layer_kind="evidence",
        z_index=SCOUT_LAYER_RANKS["events"],
        render_mode="svg_overlay",
        source_kind="runtime_evidence",
    ),
    "weather-api": AdminMapLayerSpec(
        layer_id="weather-api",
        label="Weather API",
        label_zh="氣象 API 圖層（最上層）",
        layer_kind="api",
        z_index=SCOUT_LAYER_RANKS["weather-api"],
        render_mode="api_overlay",
        source_kind="weather_api_reference",
        default_enabled=False,
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
        "rudy": (
            "pretrip.map_layer.rudy",
            source_refs.get("imagery") or source_refs.get("map_context"),
        ),
        "rudy-twmap": (
            "pretrip.map_layer.rudy_twmap",
            source_refs.get("imagery") or source_refs.get("map_context"),
        ),
        "relief": (
            "pretrip.map_layer.relief",
            source_refs.get("imagery") or source_refs.get("terrain_visualization"),
        ),
        "geology": (
            "pretrip.map_layer.geology",
            source_refs.get("imagery") or source_refs.get("map_context"),
        ),
        "topo-5k": (
            "pretrip.map_layer.topo_5k",
            source_refs.get("imagery") or source_refs.get("map_context"),
        ),
        "forest": (
            "pretrip.map_layer.forest",
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
        "soil-moisture": (
            "pretrip.map_layer.soil_moisture",
            source_refs.get("soil_moisture")
            or source_refs.get("gee_soil_moisture")
            or source_refs.get("smap_soil_moisture")
            or source_refs.get("smap_l4_corridor_summary")
            or source_refs.get("hydrology_context"),
        ),
        "antecedent-rain": (
            "pretrip.map_layer.antecedent_rain",
            source_refs.get("antecedent_rain")
            or source_refs.get("gee_antecedent_rain")
            or source_refs.get("gpm_imerg_precipitation")
            or source_refs.get("gpm_imerg_corridor_summary")
            or source_refs.get("hydrology_context"),
        ),
        "cwa-qpf": (
            "pretrip.map_layer.cwa_qpf",
            source_refs.get("cwa_qpf_grid")
            or source_refs.get("qpf_grid")
            or source_refs.get("qpf_route_timeline")
            or source_refs.get("qpf_corridor_summary"),
        ),
        "corridors": ("pretrip.map_layer.corridors", source_refs.get("map_candidates")),
        "hazards": ("pretrip.map_layer.hazards", source_refs.get("map_candidates")),
        "overpass": (
            "pretrip.map_layer.overpass",
            source_refs.get("overpass_evidence")
            or source_refs.get("overpass_map_context"),
        ),
        "route": ("pretrip.map_layer.route", source_refs.get("route_summary")),
        "completed-track": (
            "pretrip.map_layer.completed_track",
            source_refs.get("completed_trip_track"),
        ),
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
        "cwa-weather": (
            "pretrip.map_layer.cwa_weather",
            source_refs.get("cwa_weather_evidence")
            or source_refs.get("cwa_weather_imagery_manifest")
            or source_refs.get("route_weather_risk_package")
            or source_refs.get("route_weather_package")
            or source_refs.get("weather_source_manifest")
            or source_refs.get("weather_decision_candidates"),
        ),
        "mcp": ("pretrip.map_layer.mcp", source_refs.get("mcp_candidates")),
        "boss-points": (
            "pretrip.map_layer.boss_points",
            source_refs.get("boss_points_geojson") or source_refs.get("boss_points"),
        ),
        "events": ("pretrip.map_layer.events", source_refs.get("debug_projection_events")),
        "weather-api": (
            str(weather.get("source_id") or "pretrip.map_layer.weather_api"),
            str(weather.get("source_path") or source_refs.get("weather_daylight") or ""),
        ),
    }
    return _build_layers(
        PRETRIP_LAYER_CONTROL_IDS,
        sources=sources,
        available={
            "risk-score": bool(sources["risk-score"][1]),
            "risk-ribbon": bool(sources["risk-ribbon"][1]),
            "risk-heatmap": bool(sources["risk-heatmap"][1]),
            "risk-delta": bool(sources["risk-delta"][1]),
            "soil-moisture": bool(sources["soil-moisture"][1]),
            "antecedent-rain": bool(sources["antecedent-rain"][1]),
            "cwa-qpf": bool(sources["cwa-qpf"][1]),
            "cwa-weather": bool(sources["cwa-weather"][1]),
            "completed-track": False,
            "overpass": bool(sources["overpass"][1]),
            "boss-points": bool(sources["boss-points"][1]),
            "events": bool(sources["events"][1]),
        },
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
        "rudy": ("after_action.map_layer.rudy", map_source_path),
        "rudy-twmap": ("after_action.map_layer.rudy_twmap", map_source_path),
        "relief": ("after_action.map_layer.relief", map_source_path),
        "geology": ("after_action.map_layer.geology", map_source_path),
        "topo-5k": ("after_action.map_layer.topo_5k", map_source_path),
        "forest": ("after_action.map_layer.forest", map_source_path),
        "risk-score": ("after_action.map_layer.risk_score", risk_score_source_path),
        "risk-ribbon": ("after_action.map_layer.risk_ribbon", risk_ribbon_source_path),
        "risk-heatmap": ("after_action.map_layer.risk_heatmap", risk_heatmap_source_path),
        "risk-delta": ("after_action.map_layer.risk_delta", resolved_risk_delta_source),
        "soil-moisture": ("after_action.map_layer.soil_moisture", None),
        "antecedent-rain": ("after_action.map_layer.antecedent_rain", None),
        "cwa-qpf": ("after_action.map_layer.cwa_qpf", None),
        "corridors": ("after_action.map_layer.corridors", map_source_path),
        "overpass": ("after_action.map_layer.overpass", map_source_path),
        "hazards": ("after_action.map_layer.hazards", map_source_path),
        "route": ("after_action.map_layer.route", route_source_path),
        "completed-track": ("after_action.map_layer.completed_track", None),
        "reference-tracks": ("after_action.map_layer.reference_tracks", None),
        "retreat": ("after_action.map_layer.retreat", None),
        "segments": ("after_action.map_layer.segments", mission_graph_source_path),
        "checkpoints": ("after_action.map_layer.checkpoints", mission_graph_source_path),
        "pois": ("after_action.map_layer.pois", map_source_path),
        "route-notes": ("after_action.map_layer.route_notes", None),
        "cwa-weather": ("after_action.map_layer.cwa_weather", None),
        "mcp": ("after_action.map_layer.mcp", None),
        "boss-points": ("after_action.map_layer.boss_points", None),
        "terrain": ("after_action.map_layer.terrain", None),
        "events": ("after_action.map_layer.events", incident_store_path),
        "weather-api": ("after_action.map_layer.weather_api", None),
    }
    layers = _build_layers(
        AFTER_ACTION_LAYER_CONTROL_IDS,
        sources=sources,
        available={
            "terrain": False,
            "risk-score": bool(risk_score_source_path),
            "risk-ribbon": bool(risk_ribbon_source_path),
            "risk-heatmap": bool(risk_heatmap_source_path),
            "risk-delta": bool(resolved_risk_delta_source),
            "soil-moisture": False,
            "antecedent-rain": False,
            "cwa-qpf": False,
            "cwa-weather": False,
            "completed-track": False,
            "reference-tracks": False,
            "retreat": False,
            "route-notes": False,
            "mcp": False,
            "boss-points": False,
            "weather-api": False,
        },
        default_enabled={
            "risk-score": False,
            "risk-delta": False,
            "soil-moisture": False,
            "antecedent-rain": False,
            "cwa-qpf": False,
            "cwa-weather": False,
            "completed-track": True,
            "overpass": False,
            "reference-tracks": False,
            "route-notes": False,
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
            "local_raster_manifest_supported": False,
            "preferred_manifest_kind": "scout_imagery_source_registry",
            "scout_imagery_source_registry_supported": True,
            "imagery_source_registry_id": DEFAULT_REGISTRY_ID,
            "default_imagery_source_id": DEFAULT_IMAGERY_SOURCE_ID,
            "imagery_source_id": DEFAULT_IMAGERY_SOURCE_ID,
            "raster_tile_delivery": "direct_wmts_runtime",
            "local_raster_tile_cache_policy": "disabled_use_wmts_runtime",
            "external_network_required": True,
            "local_proxy_external_network_required": False,
            "remote_fetch_requires_explicit_enable": False,
            "source_registry_env": "SCOUT_IMAGERY_SOURCE_REGISTRY_PATH",
            "tile_cutting_required": False,
            "downloads_tiles_into_repo": False,
            "imagery_bbox_policy": "route_visible_bounds_wmts_runtime",
            "tile_order_warning": (
                "Imagery sources may use z/y/x or z/x/y; source registry "
                "must render templates by named z/x/y placeholders."
            ),
        }
    if layer_id in RASTER_OVERLAY_SOURCE_IDS:
        return {
            "imagery_source_registry_id": DEFAULT_REGISTRY_ID,
            "imagery_source_id": RASTER_OVERLAY_SOURCE_IDS[layer_id],
            "source_registry_env": "SCOUT_IMAGERY_SOURCE_REGISTRY_PATH",
            "raster_tile_delivery": "direct_wmts_runtime",
            "local_raster_tile_cache_policy": "disabled_use_wmts_runtime",
            "external_network_required": True,
            "local_proxy_external_network_required": False,
            "remote_fetch_requires_explicit_enable": False,
            "tile_cutting_required": False,
            "downloads_tiles_into_repo": False,
            "runtime_safety_truth": False,
            "candidate_only": True,
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
    if layer_id == "boss-points":
        return {
            "challenge_fit_layer": True,
            "route_boss_demand_layer": True,
            "candidate_only": True,
            "runtime_safety_truth": False,
            "uses_average_team_pace": False,
            "raw_health_payload_embedded": False,
            "geojson_ref_key": "boss_points_geojson_ref",
        }
    if layer_id == "soil-moisture":
        return {
            "geojson_ref_key": "soil_moisture_grid_ref",
            "provider": "google_earth_engine",
            "dataset_family": "SMAP",
            "candidate_only": True,
            "runtime_safety_truth": False,
            "secret_value_embedded": False,
            "external_network_required": False,
            "requires_prepared_workspace_artifact": True,
        }
    if layer_id == "antecedent-rain":
        return {
            "geojson_ref_key": "antecedent_rain_grid_ref",
            "provider": "google_earth_engine",
            "dataset_family": "GPM_IMERG",
            "candidate_only": True,
            "runtime_safety_truth": False,
            "secret_value_embedded": False,
            "external_network_required": False,
            "requires_prepared_workspace_artifact": True,
        }
    if layer_id == "cwa-qpf":
        return {
            "geojson_ref_key": "cwa_qpf_grid_ref",
            "provider": "cwa_opendata",
            "dataset_family": "CWA_QPF",
            "candidate_only": True,
            "runtime_safety_truth": False,
            "secret_value_embedded": False,
            "external_network_required": False,
            "requires_prepared_workspace_artifact": True,
        }
    if layer_id == "cwa-weather":
        return {
            "geojson_ref_key": "cwa_weather_evidence_ref",
            "provider": "cwa_opendata",
            "dataset_family": "CWA_WEATHER",
            "candidate_only": True,
            "runtime_safety_truth": False,
            "secret_value_embedded": False,
            "external_network_required": False,
            "requires_prepared_workspace_artifact": True,
            "source_ref_keys": [
                "route_weather_package_ref",
                "weather_source_manifest_ref",
                "weather_decision_candidates_ref",
                "cwa_weather_imagery_manifest_ref",
                "route_weather_risk_package_ref",
            ],
            "temporal_child_overlays": ["radar", "satellite"],
            "child_overlay_render_mode": "cached_georeferenced_raster",
            "imagery_manifest_endpoint_template": (
                "/admin/pretrip/projects/{project_id}/weather-imagery"
            ),
            "imagery_asset_endpoint_template": (
                "/admin/pretrip/projects/{project_id}/weather-imagery/{frame_id}"
            ),
            "opacity_controls": True,
            "timeline_controls": True,
            "animation_windows_hours": [3, 6, 9, 12],
            "admin_read_is_cache_only": True,
            "raspberry_pi_image_processing": False,
            "mobile_image_processing": False,
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
