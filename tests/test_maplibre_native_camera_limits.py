"""Camera scale must respect the visible Rudy provider's actual native pixels."""

import json
import shutil
import subprocess
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "docs/admin/scout-maplibre-evidence.js"


def _run(probe: str) -> dict:
    node = shutil.which("node")
    assert node, "Node is required for the native camera regression gate"
    program = r"""
global.window = globalThis;
global.location = {origin: "http://scout.test"};
require(process.argv[1]);
const api = ScoutMapLibreEvidence;
const definition = extra => ({layer_id: "rudy-twmap", source_id: "happyman_rudy_twmap",
  tiles: ["/tiles/{z}/{x}/{y}.png?native=1&exact=1"], minzoom: 5, maxzoom: 20, tile_size: 256, ...extra});
const layer = extra => api.normalizeRasterLayer(definition(extra));
class MapFixture {
  constructor(options) {this.options = options; this.style = options.style; this.zoom = options.zoom;
    this.maximum = options.maxZoom; this.handlers = new Map();}
  loaded() {return true;}
  on(name, ...callbacks) {if (!this.handlers.has(name)) this.handlers.set(name, []); this.handlers.get(name).push(callbacks.at(-1));}
  getSource(id) {return this.style.sources[id];}
  getLayer(id) {return this.style.layers.find(layer => layer.id === id);}
  getStyle() {return this.style;}
  getCanvas() {return {style: {}};}
  getCenter() {return {lng: 121, lat: 23};}
  getPitch() {return 0;}
  getZoom() {return this.zoom;}
  getMaxZoom() {return this.maximum;}
  setMaxZoom(value) {this.maximum = value; this.zoom = Math.min(this.zoom, value);}
  setLayoutProperty(id, name, value) {this.getLayer(id).layout[name] = value;}
  addSource(id, source) {this.style.sources[id] = source;}
  removeSource(id) {delete this.style.sources[id];}
  removeLayer(id) {this.style.layers = this.style.layers.filter(layer => layer.id !== id);}
  addLayer(layer) {this.style.layers.push(layer);}
  remove() {}
}
const container = {dataset: {}};
"""
    program += "\n(async () => {\n" + probe + "\n})().catch(error => {console.error(error); process.exit(1);});"
    result = subprocess.run([node, "-e", program, str(SCRIPT)], text=True, capture_output=True, check=True)
    return json.loads(result.stdout)


def test_native_camera_limit_uses_provider_zoom_and_tile_size() -> None:
    result = _run("""
console.log(JSON.stringify({normal: api.rasterNativeCameraPolicy([layer()]),
  large: api.rasterNativeCameraPolicy([layer({tile_size: 512})]),
  lower: api.rasterNativeCameraPolicy([layer({maxzoom: 18})]),
  hidden: api.rasterNativeCameraPolicy([layer({visible: false})])}));
""")
    assert result["normal"]["maxCameraZoom"] == 19
    assert result["normal"]["providerNativeMaxZoom"] == 20
    assert result["normal"]["worldTileSize"] == 512
    assert result["large"]["maxCameraZoom"] == 20
    assert result["lower"]["maxCameraZoom"] == 17
    assert result["hidden"]["maxCameraZoom"] == 22
    assert result["hidden"]["active"] is False


def test_renderer_constructor_and_visibility_reapply_native_cap() -> None:
    result = _run("""
const renderer = await api.createRenderer({maplibregl: {Map: MapFixture}, container, rasterLayers: [definition()]});
const initial = renderer.map.options.maxZoom;
renderer.setLayerVisibility("rudy-twmap", false); const hidden = renderer.map.getMaxZoom();
renderer.map.zoom = 22;
renderer.setLayerVisibility("rudy-twmap", true);
const restored = renderer.publishCameraLimitReceipt();
renderer.setRasterLayers([definition({maxzoom: 18})]);
console.log(JSON.stringify({initial, hidden, restored, changed: renderer.publishCameraLimitReceipt()})); renderer.destroy();
""")
    assert result["initial"] == 19
    assert result["hidden"] == 22
    assert result["restored"]["cameraZoom"] == result["restored"]["maxCameraZoom"] == 19
    assert result["restored"]["worldPixelsPerProviderPixel"] == 1
    assert result["changed"]["cameraZoom"] == result["changed"]["maxCameraZoom"] == 17


def test_prior_camera_22_with_successful_z20_tiles_is_still_eight_times_overzoom() -> None:
    result = _run("""
const map = {getZoom: () => 22, getMaxZoom: () => 22, getPitch: () => 0,
  coveringTiles: () => [{canonical: {z: 23, x: 0, y: 0}}]};
console.log(JSON.stringify(api.rasterNativeCameraReceipt(map, layer())));
""")
    assert result["worldPixelsPerProviderPixel"] == 8
    assert result["requestedAboveNativeMax"] is True
    assert result["pixelScaleScope"] == "unpitched-camera-pixel-scale"


def test_camera_cap_does_not_falsely_certify_pitched_foreground_detail() -> None:
    result = _run("""
let requestedOptions;
const map = {getZoom: () => 19, getMaxZoom: () => 19, getPitch: () => 58, terrain: {decoded: true},
  coveringTiles: options => {requestedOptions = options; return [18, 20, 21].map(z => ({canonical: {z, x: 0, y: 0}}));}};
console.log(JSON.stringify({receipt: api.rasterNativeCameraReceipt(map, layer()), requestedOptions}));
""")
    assert result["receipt"]["worldPixelsPerProviderPixel"] == 1
    assert result["receipt"]["pixelScaleScope"] == "camera-world-scale-only"
    assert result["receipt"]["requestedNativeZooms"] == [18, 20, 21]
    assert result["receipt"]["requestedAboveNativeMax"] is True
    assert result["requestedOptions"]["maxzoom"] > 20
    assert result["requestedOptions"]["terrain"] == {"decoded": True}


def test_box_and_click_zoom_follow_actual_native_max_without_zooming_out_at_the_cap() -> None:
    result = _run("""
const renderer = await api.createRenderer({maplibregl: {Map: MapFixture}, container, rasterLayers: [definition()]});
const actions = [];
renderer.map.unproject = point => ({lng: point[0], lat: point[1]});
renderer.map.fitBounds = (bounds, options) => actions.push({kind: 'box', from: renderer.map.zoom, bounds, ceiling: options.maxZoom});
renderer.map.easeTo = options => actions.push({kind: 'click', from: renderer.map.zoom, ceiling: options.zoom});
const event = {pointerId: 1, preventDefault() {}, stopPropagation() {}};
for (const zoom of [13, 17.5, 19]) {
  for (const reverse of [false, true]) {
    renderer.map.zoom = zoom;
    renderer.rectangleZoomSelection = {pointerId: 1, moved: true,
      start: reverse ? {x: 30, y: 30} : {x: 10, y: 10}, current: reverse ? {x: 10, y: 10} : {x: 30, y: 30}};
    renderer.finishRectangleZoom(event);
  }
  renderer.rectangleZoomSelection = {pointerId: 1, moved: false, start: {x: 10, y: 10}};
  renderer.finishRectangleZoom(event);
}
console.log(JSON.stringify({actions})); renderer.destroy();
""")
    for action in result["actions"]:
        assert action["ceiling"] == min(action["from"] + (2 if action["kind"] == "box" else 1), 19)
        assert action["ceiling"] >= action["from"]
    boxes = [action for action in result["actions"] if action["kind"] == "box"]
    for forward, reverse in zip(boxes[::2], boxes[1::2]):
        assert forward == reverse, "The existing direction contract must remain unchanged pending arbitration"
