import json
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "docs" / "admin" / "scout-maplibre-evidence.js"


def _run_order_probe() -> dict[str, object]:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is required for map layer order diagnostics")
    probe = r"""
const {JSDOM} = require("jsdom");
const dom = new JSDOM("<!doctype html><body></body>", {url: "http://127.0.0.1/admin"});
global.window = dom.window;
global.document = dom.window.document;
require(process.argv[1]);
const adapter = global.window.ScoutMapLibreEvidence;

function svg(markup) {
  const template = document.createElement("template");
  template.innerHTML = markup.trim();
  return template.content.querySelector("svg");
}

const required = ["imagery", "route", "segments", "checkpoints"];
const expected = ["imagery", "route", "segments", "checkpoints"];
const validSvg = adapter.inspectSvgLayerOrder(svg(`
  <svg>
    <defs><g data-layer-group="route"><path d="M0 0 L1 1"></path></g></defs>
    <g data-layer-group="imagery"><image href="/tiles/13/0/0.png"></image></g>
    <g data-layer-group="route"><path d="M0 0 L10 10"></path></g>
    <g data-layer-group="segments"><path d="M0 2 L10 12"></path></g>
    <g data-layer-group="checkpoints"><circle cx="4" cy="5" r="3"></circle></g>
  </svg>
`), {requiredLayerIds: required, expectedLayerOrder: expected});

const rasterOverRoute = adapter.inspectSvgLayerOrder(svg(`
  <svg>
    <g data-layer-group="route"><path d="M0 0 L10 10"></path></g>
    <g data-layer-group="imagery"><image href="/tiles/13/0/0.png"></image></g>
    <g data-layer-group="checkpoints"><circle cx="4" cy="5" r="3"></circle></g>
  </svg>
`), {requiredLayerIds: ["imagery", "route", "checkpoints"], expectedLayerOrder: ["imagery", "route", "checkpoints"]});

const missingDuplicate = adapter.inspectSvgLayerOrder(svg(`
  <svg>
    <g data-layer-group="imagery"><image href="/tiles/13/0/0.png"></image></g>
    <g data-layer-group="imagery"><image href="/tiles/13/0/1.png"></image></g>
    <g data-layer-group="route"><path d="M0 0 L10 10"></path></g>
  </svg>
`), {requiredLayerIds: required, expectedLayerOrder: expected});

const emptySvg = adapter.inspectSvgLayerOrder(svg("<svg><g data-layer-group='route'></g></svg>"));
const nativeSvg = adapter.inspectSvgLayerOrder(svg(`
  <svg>
    <image data-dashboard-rudy-tile="true" data-map-render-kind="tile" data-map-tile-source="rudy-twmap" href="/tiles/13/0/0.png"></image>
    <path class="navigation-route" data-dashboard-map-hint-source="navigation-main-route-evidence" d="M0 0 L10 10"></path>
    <path class="route-structure" d="M1 1 L8 8"></path>
    <rect x="0" y="0" width="2" height="2"></rect>
    <circle data-dashboard-context-points="true" cx="5" cy="5" r="2"></circle>
    <circle data-pace-checkpoint-id="pace-cp1" cx="6" cy="6" r="2"></circle>
    <circle data-permission-map-anchor="day-1-cp1" cx="7" cy="7" r="2"></circle>
  </svg>
`));
const hiddenRasterOverRoute = adapter.inspectSvgLayerOrder(svg(`
  <svg>
    <path data-dashboard-map-hint-source="overview-route-evidence" d="M0 0 L10 10"></path>
    <g class="is-hidden" data-layer-group="imagery"><image href="/tiles/13/0/0.png"></image></g>
    <circle data-dashboard-context-points="true" cx="5" cy="5" r="2"></circle>
  </svg>
`));
const equalRankSvg = adapter.inspectSvgLayerOrder(svg(`
  <svg>
    <g data-layer-group="relief"><image href="/tiles/13/0/0.png"></image></g>
    <g data-layer-group="rudy-twmap"><image href="/tiles/13/0/1.png"></image></g>
    <g data-layer-group="route"><path d="M0 0 L10 10"></path></g>
    <g data-layer-group="checkpoints"><circle cx="5" cy="5" r="2"></circle></g>
  </svg>
`), {expectedLayerOrder: [["rudy-twmap", "relief"], "route", "checkpoints"]});
const ariaHiddenVisibleSvg = adapter.inspectSvgLayerOrder(svg(`
  <svg>
    <image aria-hidden="true" data-map-render-kind="tile" data-map-tile-source="rudy-twmap" style="opacity:0.5" href="/tiles/13/0/0.png"></image>
    <path data-dashboard-map-hint-source="overview-route-evidence" d="M0 0 L10 10"></path>
    <circle data-dashboard-context-points="true" cx="5" cy="5" r="2"></circle>
  </svg>
`));
const groupedNativeCheckpoint = adapter.inspectSvgLayerOrder(svg(`
  <svg>
    <g data-pace-checkpoint-id="cp-1"><circle r="3"></circle></g>
    <path data-navigation-route-path="true" d="M0 0 L10 10"></path>
  </svg>
`));
const nestedRasterBeforeRoute = adapter.inspectSvgLayerOrder(svg(`
  <svg><g data-layer-group="route">
    <image href="/tiles/base.png"></image>
    <path d="M0 0 L10 10"></path>
  </g></svg>
`));
const repeatedRasterViolation = adapter.inspectSvgLayerOrder(svg(`
  <svg>
    <path data-navigation-route-path="true" d="M0 0 L10 10"></path>
    <g data-layer-group="cwa-weather">
      <image href="/tiles/rain-1.png"></image>
      <image href="/tiles/rain-2.png"></image>
    </g>
  </svg>
`));
const backgroundOnlySvg = adapter.inspectSvgLayerOrder(svg(`
  <svg><rect width="100" height="100"></rect><image href="/tiles/base.png"></image></svg>
`), {requireRoute: false});
const terrainGeometrySvg = adapter.inspectSvgLayerOrder(svg(`
  <svg><image href="/tiles/base.png"></image><path d="M0 0 L10 10"></path></svg>
`), {requireRoute: false});

const featureCollection = adapter.createEvidenceFeatureCollection([
  adapter.createEvidenceFeature({
    source_id: "route.fixture",
    candidate_only: true,
    runtime_safety_truth: false
  }, {
    layerId: "route",
    geometry: {type: "MultiLineString", coordinates: [[[121, 24], [121.1, 24.1]]]}
  }),
  adapter.createEvidenceFeature({
    source_id: "checkpoint.fixture",
    candidate_only: true,
    runtime_safety_truth: false
  }, {
    layerId: "checkpoints",
    geometry: {type: "Point", coordinates: [121, 24]}
  })
]);
const rasterLayer = adapter.normalizeRasterLayer({
  layer_id: "rudy-twmap",
  source_id: "happyman_rudy_twmap",
  tiles: ["/admin/tiles/imagery/demo/imagery/{z}/{x}/{y}.png"],
  visible: true,
  candidate_only: true,
  runtime_safety_truth: false
});
const validMapLibre = adapter.inspectMapLibreLayerOrder(
  adapter.createEvidenceStyle(featureCollection, {rasterLayers: [rasterLayer]})
);

const invalidStyle = adapter.createEvidenceStyle(featureCollection);
invalidStyle.sources[rasterLayer.map_source_id] = {type: "raster", tiles: ["/admin/tiles/{z}/{x}/{y}.png"]};
invalidStyle.layers.push({
  id: rasterLayer.map_layer_id,
  type: "raster",
  source: rasterLayer.map_source_id,
  layout: {visibility: "visible"}
});
const mapLibreRasterOverRoute = adapter.inspectMapLibreLayerOrder(invalidStyle);
const duplicateMapLibre = adapter.inspectMapLibreLayerOrder({
  ...adapter.createEvidenceStyle(featureCollection, {rasterLayers: [rasterLayer]}),
  layers: [
    ...adapter.createEvidenceStyle(featureCollection, {rasterLayers: [rasterLayer]}).layers,
    {id: "scout-evidence-line", type: "line", source: "scout-evidence"}
  ]
});
const emptyMapLibre = adapter.inspectMapLibreLayerOrder({version: 8, sources: {}, layers: []});
const missingRouteMapLibre = adapter.inspectMapLibreLayerOrder({
  version: 8,
  sources: {"scout-evidence": {type: "geojson", data: {type: "FeatureCollection", features: [
    {type: "Feature", properties: {layer_id: "route"}, geometry: {type: "Point", coordinates: [121, 24]}}
  ]}}},
  layers: [
    {id: "route-label", type: "symbol", source: "scout-evidence"},
    {id: "route-fill", type: "fill", source: "scout-evidence"},
    {id: "scout-evidence-background", type: "background"}
  ]
});
const malformedGetStyle = adapter.inspectMapLibreLayerOrder({
  getStyle() {
    throw new Error("style unavailable");
  }
});

process.stdout.write(JSON.stringify({
  validSvg,
  rasterOverRoute,
  missingDuplicate,
  emptySvg,
  nativeSvg,
  hiddenRasterOverRoute,
  equalRankSvg,
  ariaHiddenVisibleSvg,
  groupedNativeCheckpoint,
  nestedRasterBeforeRoute,
  repeatedRasterViolation,
  backgroundOnlySvg,
  terrainGeometrySvg,
  validMapLibre,
  mapLibreRasterOverRoute,
  duplicateMapLibre,
  emptyMapLibre,
  missingRouteMapLibre,
  malformedGetStyle
}));
"""
    completed = subprocess.run(
        [node, "-e", probe, str(SCRIPT)],
        check=True,
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    return json.loads(completed.stdout)


def test_svg_layer_order_passes_for_canonical_paint_order() -> None:
    result = _run_order_probe()["validSvg"]

    assert result["status"] == "passed"
    assert result["renderer"] == "svg"
    layer_ids = [layer["id"] for layer in result["layers"]]
    assert layer_ids.index("imagery") < layer_ids.index("route")
    assert layer_ids.index("route") < layer_ids.index("segments")
    assert layer_ids.index("segments") < layer_ids.index("checkpoints")
    assert result["violations"] == []
    assert result["gaps"] == []


def test_svg_layer_order_fails_raster_above_route() -> None:
    result = _run_order_probe()["rasterOverRoute"]

    assert result["status"] == "failed"
    codes = {violation["code"] for violation in result["violations"]}
    assert "background_over_route" in codes
    assert "expected_layer_order_inversion" in codes


def test_svg_layer_order_fails_missing_and_duplicate_required_groups() -> None:
    result = _run_order_probe()["missingDuplicate"]

    assert result["status"] == "failed"
    codes = {violation["code"] for violation in result["violations"]}
    assert "missing_required_layer" in codes
    assert "duplicate_layer_group" in codes


def test_empty_svg_content_warns_without_vacuous_pass() -> None:
    result = _run_order_probe()["emptySvg"]

    assert result["status"] == "warning"
    assert result["violations"] == []
    assert result["gaps"]


def test_native_svg_semantic_attrs_provide_stable_roles_without_layer_groups() -> None:
    result = _run_order_probe()["nativeSvg"]

    assert result["status"] == "passed"
    roles = {layer["id"]: layer["role"] for layer in result["layers"]}
    assert roles["navigation-main-route-evidence"] == "route"
    assert roles["rect"] == "unknown"
    assert roles["dashboard-context-points"] == "checkpoint"
    assert "route" in {layer["role"] for layer in result["layers"]}
    assert "checkpoint" in {layer["role"] for layer in result["layers"]}


def test_hidden_svg_raster_is_still_order_checked() -> None:
    result = _run_order_probe()["hiddenRasterOverRoute"]

    assert result["status"] == "failed"
    assert any(
        violation["code"] == "background_over_route"
        for violation in result["violations"]
    )
    assert any(
        layer["id"] == "imagery"
        and layer["visible"] is False
        and layer["hasContent"] is True
        for layer in result["layers"]
    )


def test_svg_expected_order_allows_equal_rank_groups() -> None:
    result = _run_order_probe()["equalRankSvg"]

    assert result["status"] == "passed"
    assert result["violations"] == []


def test_svg_aria_hidden_and_fractional_opacity_do_not_hide_tiles() -> None:
    result = _run_order_probe()["ariaHiddenVisibleSvg"]

    assert result["status"] == "passed"
    assert any(
        layer["id"] == "rudy-twmap"
        and layer["visible"] is True
        and layer["hasContent"] is True
        for layer in result["layers"]
    )


def test_maplibre_layer_order_passes_for_adapter_style() -> None:
    result = _run_order_probe()["validMapLibre"]

    assert result["status"] == "passed"
    layer_ids = [layer["id"] for layer in result["layers"]]
    assert layer_ids.index("scout-raster-layer-rudy-twmap") < layer_ids.index("scout-evidence-line")
    assert layer_ids.index("scout-evidence-line") < layer_ids.index("scout-evidence-point")
    assert result["violations"] == []
    assert result["gaps"] == []


def test_native_checkpoint_group_is_checked_against_later_route() -> None:
    result = _run_order_probe()["groupedNativeCheckpoint"]

    assert result["status"] == "failed"
    assert result["violations"][0]["code"] == "route_over_checkpoint_anchor"


def test_nested_raster_before_route_uses_actual_leaf_paint_order() -> None:
    result = _run_order_probe()["nestedRasterBeforeRoute"]

    assert result["status"] == "passed"


def test_repeated_layer_violations_are_aggregated_without_losing_occurrences() -> None:
    result = _run_order_probe()["repeatedRasterViolation"]

    assert result["status"] == "failed"
    assert len(result["violations"]) == 1
    assert result["violations"][0]["occurrences"] == 2
    assert "cwa-weather" in result["violations"][0]["detail"]


def test_non_route_view_with_only_background_does_not_pass() -> None:
    result = _run_order_probe()["backgroundOnlySvg"]

    assert result["status"] == "warning"
    assert result["gaps"]
    assert _run_order_probe()["terrainGeometrySvg"]["status"] == "passed"


def test_maplibre_layer_order_fails_raster_above_route() -> None:
    result = _run_order_probe()["mapLibreRasterOverRoute"]

    assert result["status"] == "failed"
    assert any(
        violation["code"] == "background_over_route"
        for violation in result["violations"]
    )


def test_maplibre_duplicate_style_ids_fail() -> None:
    result = _run_order_probe()["duplicateMapLibre"]

    assert result["status"] == "failed"
    assert any(
        violation["code"] == "duplicate_style_layer_id"
        for violation in result["violations"]
    )


def test_empty_or_missing_maplibre_route_warns_without_vacuous_pass() -> None:
    result = _run_order_probe()

    assert result["emptyMapLibre"]["status"] == "warning"
    assert result["emptyMapLibre"]["gaps"]
    assert result["missingRouteMapLibre"]["status"] == "warning"
    assert any("route" in gap for gap in result["missingRouteMapLibre"]["gaps"])
    assert result["malformedGetStyle"]["status"] == "warning"
    assert any("getStyle failed" in gap for gap in result["malformedGetStyle"]["gaps"])
