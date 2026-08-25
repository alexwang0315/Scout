import json
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "docs" / "admin" / "scout-maplibre-evidence.js"
LOCAL_MAPLIBRE_MODULE_URL = "/admin/vendor/maplibre-gl/6.2.0/maplibre-gl.mjs"


def _run_adapter_probe() -> dict[str, object]:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is required for the browser adapter contract probe")
    probe = """
global.window = globalThis;
require(process.argv[1]);
const adapter = globalThis.ScoutMapLibreEvidence;
const identity = adapter.normalizeEvidenceIdentity({
  source_id: "segment.source.001",
  candidate_id: "segment.candidate.001",
  candidate_only: true,
  runtime_safety_truth: false
}, {layerId: "segments", ordinal: 3});
const index = adapter.buildEvidenceIndex([{
  type: "Feature",
  id: identity.feature_id,
  properties: {...identity, map_refs: ["route-progress"], segment_id: "seg.001"},
  geometry: {type: "LineString", coordinates: [[121, 24], [121.1, 24.1]]}
}]);
const routeFeature = adapter.createEvidenceFeature({
  source_id: "artifact.gpx.route",
  candidate_only: true,
  runtime_safety_truth: false,
  display_label: "Prepared route"
}, {
  layerId: "route",
  ordinal: 0,
  geometry: {type: "LineString", coordinates: [[121, 24], [121.1, 24.1]]},
  properties: {display_label: "Prepared route"}
});
const featureCollection = adapter.createEvidenceFeatureCollection([routeFeature]);
const style = adapter.createEvidenceStyle(featureCollection);
const lineColorExpression = style.layers.find(layer => layer.id === adapter.layerIds.line).paint["line-color"];
const evidenceColors = {};
for (let index = 2; index < lineColorExpression.length - 1; index += 2) {
  evidenceColors[lineColorExpression[index]] = lineColorExpression[index + 1];
}
const rasterLayer = adapter.normalizeRasterLayer({
  layer_id: "rudy-twmap",
  source_id: "happyman_rudy_twmap",
  tiles: ["/admin/tiles/imagery/demo/imagery/{z}/{x}/{y}.png?source_id=happyman_rudy_twmap&native=1"],
  minzoom: 5,
  maxzoom: 20,
  opacity: 0.9,
  visible: true,
  candidate_only: true,
  runtime_safety_truth: false
});
const terrainImageLayer = adapter.normalizeRasterLayer({
  layer_id: "terrain-slope-shading",
  control_layer_id: "terrain",
  source_id: "terrain_visualization.overlay.slope_shading",
  source_type: "image",
  image_url: "/admin/pretrip/projects/demo/terrain-overlays/slope_shading.png",
  image_coordinates: [[121, 24.1], [121.1, 24.1], [121.1, 24], [121, 24]],
  opacity: 0.78,
  visible: true,
  candidate_only: true,
  runtime_safety_truth: false
});
const cwaImageLayer = adapter.normalizeRasterLayer({
  layer_id: "cwa-weather-radar",
  control_layer_id: "cwa-weather",
  source_id: "radar.integrated.taiwan.transparent.fixture",
  source_type: "image",
  image_url: "/admin/pretrip/projects/demo/weather-imagery/radar.fixture",
  image_coordinates: [[120, 25.5], [122, 25.5], [122, 21.5], [120, 21.5]],
  opacity: 0.62,
  visible: true,
  render_position: "overlay",
  candidate_only: true,
  runtime_safety_truth: false
});
const rasterStyle = adapter.createEvidenceStyle(featureCollection, {
  rasterLayers: [rasterLayer, terrainImageLayer, cwaImageLayer]
});
const result = {
  normalized: [
    adapter.normalizeRendererPreference("AUTO"),
    adapter.normalizeRendererPreference("maplibre"),
    adapter.normalizeRendererPreference("svg"),
    adapter.normalizeRendererPreference("unexpected")
  ],
  forcedSvg: adapter.resolveRenderer({requested: "svg", webglAvailable: true}),
  autoMapLibre: adapter.resolveRenderer({requested: "auto", webglAvailable: true}),
  unavailable: adapter.resolveRenderer({requested: "maplibre", webglAvailable: false}),
  identity,
  partialIdentity: adapter.normalizeEvidenceIdentity({}, {layerId: "route-notes", ordinal: 8}),
  index: {
    size: index.size,
    candidate: index.resolve("segment.candidate.001"),
    source: index.resolve("segment.source.001"),
    mapRef: index.resolve("route-progress"),
    segment: index.resolve("seg.001"),
    missing: index.resolve("missing")
  },
  routeFeature,
  collectionFeatureCount: featureCollection.features.length,
  style: {
    version: style.version,
    sourceType: style.sources[adapter.sourceId].type,
    sourceFeatureCount: style.sources[adapter.sourceId].data.features.length,
    layerIds: style.layers.map(layer => layer.id),
    evidenceColors
  },
  rasterLayer,
  terrainImageLayer,
  cwaImageLayer,
  rasterStateTransitions: {
    hiddenLoaded: adapter.rasterLayerEventPatch({visible: false, error_count: 0}, "source_loaded"),
    visibleLoaded: adapter.rasterLayerEventPatch({visible: true, error_count: 0}, "source_loaded"),
    hiddenError: adapter.rasterLayerEventPatch({visible: false, error_count: 2}, "tile_error"),
    visibleError: adapter.rasterLayerEventPatch({visible: true, error_count: 2}, "tile_error")
  },
  rasterStyle: {
    source: rasterStyle.sources[rasterLayer.map_source_id],
    layer: rasterStyle.layers.find(layer => layer.id === rasterLayer.map_layer_id),
    terrainSource: rasterStyle.sources[terrainImageLayer.map_source_id],
    terrainLayer: rasterStyle.layers.find(layer => layer.id === terrainImageLayer.map_layer_id),
    cwaSource: rasterStyle.sources[cwaImageLayer.map_source_id],
    cwaLayer: rasterStyle.layers.find(layer => layer.id === cwaImageLayer.map_layer_id),
    layerIds: rasterStyle.layers.map(layer => layer.id)
  },
  collectionBounds: adapter.featureCollectionBounds(featureCollection)
};
try {
  adapter.normalizeEvidenceIdentity({
    candidate_id: "invalid.candidate",
    candidate_only: true,
    runtime_safety_truth: true
  }, {layerId: "hazards", ordinal: 0});
  result.invariantError = null;
} catch (error) {
  result.invariantError = error.message;
}
try {
  adapter.createEvidenceFeature({}, {
    layerId: "invalid",
    geometry: {type: "GeometryCollection", geometries: []}
  });
  result.geometryError = null;
} catch (error) {
  result.geometryError = error.message;
}
try {
  adapter.normalizeRasterLayer({
    layer_id: "unsafe-file",
    tiles: ["file:///private/dem/{z}/{x}/{y}.png"]
  });
  result.rasterUrlError = null;
} catch (error) {
  result.rasterUrlError = error.message;
}
try {
  adapter.normalizeRasterLayer({
    layer_id: "unsafe-authority",
    tiles: ["/admin/tiles/{z}/{x}/{y}.png"],
    candidate_only: true,
    runtime_safety_truth: true
  });
  result.rasterInvariantError = null;
} catch (error) {
  result.rasterInvariantError = error.message;
}
try {
  adapter.normalizeRasterLayer({
    layer_id: "invalid-position",
    tiles: ["/admin/tiles/{z}/{x}/{y}.png"],
    render_position: "floating"
  });
  result.rasterPositionError = null;
} catch (error) {
  result.rasterPositionError = error.message;
}
process.stdout.write(JSON.stringify(result));
"""
    completed = subprocess.run(
        [node, "-e", probe, str(SCRIPT)],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def test_adapter_defaults_to_same_origin_maplibre_distribution():
    source = SCRIPT.read_text(encoding="utf-8")

    assert LOCAL_MAPLIBRE_MODULE_URL in source
    assert "unpkg.com/maplibre-gl" not in source


def test_renderer_resolution_is_typed_and_fail_closed() -> None:
    result = _run_adapter_probe()

    assert result["normalized"] == ["auto", "maplibre", "svg", "auto"]
    assert result["forcedSvg"] == {
        "requested": "svg",
        "active": "svg",
        "state": "ready",
        "reason": "forced_svg",
    }
    assert result["autoMapLibre"] == {
        "requested": "auto",
        "active": "maplibre",
        "state": "loading",
        "reason": "maplibre_selected",
    }
    assert result["unavailable"] == {
        "requested": "maplibre",
        "active": "svg",
        "state": "degraded",
        "reason": "webgl_unavailable",
    }


def test_evidence_identity_is_stable_partial_and_candidate_safe() -> None:
    result = _run_adapter_probe()

    assert result["identity"] == {
        "source_id": "segment.source.001",
        "artifact_id": None,
        "candidate_id": "segment.candidate.001",
        "layer_id": "segments",
        "feature_id": "segment.candidate.001",
        "identity_key": "segments:segment.candidate.001",
        "identity_status": "source_bound",
        "geometry_ref": None,
        "candidate_only": True,
        "runtime_safety_truth": False,
        "operational": False,
        "selected_evidence": False,
        "highlight_state": "default",
    }
    assert result["partialIdentity"]["identity_status"] == "renderer_local"
    assert result["partialIdentity"]["feature_id"] == "renderer-local:route-notes:8"
    assert result["partialIdentity"]["artifact_id"] is None
    assert result["invariantError"] == "candidate_runtime_truth_conflict"
    assert result["index"] == {
        "size": 1,
        "candidate": ["segment.candidate.001"],
        "source": ["segment.candidate.001"],
        "mapRef": ["segment.candidate.001"],
        "segment": ["segment.candidate.001"],
        "missing": [],
    }


def test_geojson_adapter_builds_bounded_sources_and_layers() -> None:
    result = _run_adapter_probe()

    feature = result["routeFeature"]
    assert feature["type"] == "Feature"
    assert feature["id"] == "route:artifact.gpx.route"
    assert feature["bbox"] == [121, 24, 121.1, 24.1]
    assert feature["properties"]["layer_id"] == "route"
    assert feature["properties"]["candidate_only"] is True
    assert feature["properties"]["runtime_safety_truth"] is False
    assert result["collectionFeatureCount"] == 1
    assert result["style"]["version"] == 8
    assert result["style"]["sourceType"] == "geojson"
    assert result["style"]["sourceFeatureCount"] == 1
    assert result["style"]["layerIds"] == [
        "scout-evidence-background",
        "scout-evidence-fill",
        "scout-evidence-line",
        "scout-evidence-point",
        "scout-evidence-overlay-fill",
    ]
    assert result["style"]["evidenceColors"] | {
        "qgis-route": "#e00067",
        "qgis-ridge-lines": "#ffb000",
        "qgis-valley-lines": "#38a7c7",
        "qgis-stream-network": "#1769aa",
    } == result["style"]["evidenceColors"]
    assert result["collectionBounds"] == [121, 24, 121.1, 24.1]
    assert result["geometryError"] == "unsupported_geometry_type:GeometryCollection"


def test_raster_adapter_is_bounded_candidate_only_and_renderer_ordered() -> None:
    result = _run_adapter_probe()

    raster = result["rasterLayer"]
    assert raster["layer_id"] == "rudy-twmap"
    assert raster["map_source_id"] == "scout-raster-rudy-twmap"
    assert raster["map_layer_id"] == "scout-raster-layer-rudy-twmap"
    assert raster["network_scope"] == "same_origin"
    assert raster["candidate_only"] is True
    assert raster["runtime_safety_truth"] is False
    assert raster["operational"] is False
    assert raster["visualization_only"] is True
    assert raster["adds_source_resolution"] is False
    assert result["rasterUrlError"] == "unsupported_raster_tile_url"
    assert result["rasterInvariantError"] == "candidate_runtime_truth_conflict"
    assert result["rasterPositionError"] == "invalid_raster_render_position"

    terrain = result["terrainImageLayer"]
    assert terrain["layer_id"] == "terrain-slope-shading"
    assert terrain["control_layer_id"] == "terrain"
    assert terrain["source_type"] == "image"
    assert terrain["image_url"].endswith("/terrain-overlays/slope_shading.png")
    assert terrain["image_coordinates"] == [
        [121, 24.1],
        [121.1, 24.1],
        [121.1, 24],
        [121, 24],
    ]
    assert terrain["candidate_only"] is True
    assert terrain["runtime_safety_truth"] is False

    cwa = result["cwaImageLayer"]
    assert cwa["control_layer_id"] == "cwa-weather"
    assert cwa["render_position"] == "overlay"
    assert cwa["candidate_only"] is True
    assert cwa["runtime_safety_truth"] is False

    source = result["rasterStyle"]["source"]
    assert source["type"] == "raster"
    assert source["tileSize"] == 256
    assert source["tiles"] == raster["tiles"]
    layer = result["rasterStyle"]["layer"]
    assert layer["type"] == "raster"
    assert layer["layout"]["visibility"] == "visible"
    terrain_source = result["rasterStyle"]["terrainSource"]
    assert terrain_source["type"] == "image"
    assert terrain_source["url"].endswith("/terrain-overlays/slope_shading.png")
    assert terrain_source["coordinates"] == terrain["image_coordinates"]
    terrain_layer = result["rasterStyle"]["terrainLayer"]
    assert terrain_layer["metadata"]["scout:control_layer_id"] == "terrain"
    assert terrain_layer["paint"]["raster-resampling"] == "nearest"
    cwa_source = result["rasterStyle"]["cwaSource"]
    assert cwa_source["type"] == "image"
    cwa_layer = result["rasterStyle"]["cwaLayer"]
    assert cwa_layer["metadata"]["scout:render_position"] == "overlay"
    layer_ids = result["rasterStyle"]["layerIds"]
    assert layer_ids.index(raster["map_layer_id"]) < layer_ids.index(
        "scout-evidence-fill"
    )
    assert layer_ids.index(cwa["map_layer_id"]) > layer_ids.index(
        "scout-evidence-point"
    )
    assert result["rasterStateTransitions"] == {
        "hiddenLoaded": None,
        "visibleLoaded": {"state": "available", "reason": "source_loaded"},
        "hiddenError": None,
        "visibleError": {
            "state": "degraded",
            "reason": "tile_load_failed",
            "error_count": 3,
        },
    }


def test_renderer_contract_includes_hover_labels_grouped_layers_and_box_zoom() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert 'className = "scout-maplibre-selection-label"' in source
    assert "onFeatureHover = null" in source
    assert "onFeatureLeave = null" in source
    assert 'this.map.on("mousemove", layerId' in source
    assert "setInteractionMode(mode)" in source
    assert 'this.container.dataset.maplibreInteractionMode = nextMode' in source
    assert "beginRectangleZoom(event)" in source
    assert "finishRectangleZoom(event)" in source
    assert 'this.map.fitBounds([[west, south], [east, north]]' in source
    assert "layer.control_layer_id === requestedLayerId" in source
    assert "setRasterLayers(definitions = [])" in source
    assert 'overlayFill: "scout-evidence-overlay-fill"' in source
    assert "EVIDENCE_LAYER_IDS.overlayFill" in source
