"""The first real evidence viewport must load before the adapter reports ready.

This is a public-API ordering replay, not a performance or live-browser claim.
The actual failure receipt remains in the qualification artifact directory.
"""

import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "docs/admin/scout-maplibre-evidence.js"


def _run(probe: str) -> dict:
    node = shutil.which("node")
    assert node, "Node is required for MapLibre initial-view regression checks"
    program = r"""
global.window = globalThis;
global.location = {origin: "http://scout.test"};
let now = 1000, nextTimer = 1;
Date.now = () => now;
const timers = new Map();
global.setTimeout = (fn, delay) => {const id = nextTimer++; timers.set(id, {fn, delay}); return id;};
global.clearTimeout = id => timers.delete(id);
require(process.argv[1]);
const api = ScoutMapLibreEvidence;
let renderer = null, changes = [], statuses = [];
class MapFixture {
  constructor(options) {
    this.options = options; this.style = options.style; this.handlers = new Map();
    this.ready = false; this.tilesReady = false; this.styleReady = false; this.removed = 0;
    this.zoom = options.zoom; this.maximum = options.maxZoom;
    this.center = options.center;
    if (options.bounds) {
      this.center = options.bounds[0].map((n, i) => (n + options.bounds[1][i]) / 2);
      this.zoom = Math.min(options.fitBoundsOptions.maxZoom, options.maxZoom, 12);
    }
    this.initialCamera = {center: this.center, zoom: this.zoom, bounds: options.bounds ?? null};
    this.source = {...this.style.sources[api.sourceId], setData: data => {
      changes.push({kind: "setData", beforeLoaded: this.ready});
      this.source.data = data; this.ready = this.tilesReady = this.styleReady = false;
    }};
  }
  loaded() {return this.ready;}
  isStyleLoaded() {return this.styleReady;}
  areTilesLoaded() {return this.tilesReady;}
  isSourceLoaded() {return this.tilesReady;}
  getStyle() {return this.style;}
  getSource(id) {return id === api.sourceId ? this.source : this.style.sources[id];}
  getLayer(id) {return this.style.layers.find(layer => layer.id === id);}
  getCanvas() {return {style: {}, width: 2404, height: 1552};}
  getCenter() {return {lng: this.center[0], lat: this.center[1]};}
  getZoom() {return this.zoom;}
  getPitch() {return 0;}
  getMaxZoom() {return this.maximum;}
  setMaxZoom(zoom) {this.maximum = zoom; this.zoom = Math.min(this.zoom, zoom);}
  setLayoutProperty(id, key, value) {this.getLayer(id).layout[key] = value;}
  on(name, ...values) {if (!this.handlers.has(name)) this.handlers.set(name, new Set()); this.handlers.get(name).add(values.at(-1));}
  off(name, fn) {this.handlers.get(name)?.delete(fn);}
  fire(name, event = {}) {for (const fn of [...(this.handlers.get(name) || [])]) fn(event);}
  fitBounds(bounds, options) {
    changes.push({kind: "fitBounds", bounds, options, beforeLoaded: this.ready});
    this.ready = this.tilesReady = this.styleReady = false;
  }
  easeTo(options) {changes.push({kind: "easeTo", options}); this.ready = this.tilesReady = false;}
  remove() {this.removed++; this.fire("remove");}
}
const host = {dataset: {}, getBoundingClientRect: () => ({width: 1204, height: 778})};
const makeFeature = (id, coordinates, type = "LineString") => api.createEvidenceFeature(
  {source_id: id, candidate_only: true, runtime_safety_truth: false},
  {layerId: "route", geometry: {type, coordinates}});
const route = makeFeature("route-a", [[121.05, 23.41], [121.16, 23.49]]);
const side = makeFeature("route-b", [[121.15, 23.48], [121.2, 23.5]]);
const collection = api.createEvidenceFeatureCollection([route, side]);
const options = extra => ({maplibregl: {Map: MapFixture}, container: host, timeoutMs: 20000,
  onCreated: value => {renderer = value;},
  onStatus: status => statuses.push({state: status.state, mapLoaded: renderer?.map?.loaded() ?? null}),
  ...extra});
const load = () => {
  renderer.map.ready = renderer.map.styleReady = renderer.map.tilesReady = true;
  renderer.map.fire("load");
};
const expire = () => {const timer = [...timers.values()][0]; now += timer.delay; timer.fn();};
"""
    program += "\n(async () => {\n" + probe + "\n})().catch(e => {console.error(e); process.exit(1);});"
    result = subprocess.run([node, "-e", program, str(SCRIPT)], text=True, capture_output=True, check=True)
    return json.loads(result.stdout)


def test_first_source_cohort_uses_full_evidence_bounds_before_load() -> None:
    result = _run("""
const pending = api.createRenderer(options(), collection);
const initial = renderer.map.initialCamera, constructorOptions = renderer.map.options;
load(); await pending;
console.log(JSON.stringify({initial, fit: constructorOptions.fitBoundsOptions, changes, statuses,
  sourceData: renderer.map.source.data, featureCount: host.dataset.maplibreFeatureCount}));
renderer.destroy();
""")
    assert result["initial"]["bounds"] == [[121.05, 23.41], [121.2, 23.5]]
    assert result["fit"] == {"padding": 72, "maxZoom": 16, "duration": 0}
    assert result["changes"] == [], "First load must not be invalidated by duplicate setData or a new viewport"
    assert result["statuses"][-1] == {"state": "ready", "mapLoaded": True}
    assert result["featureCount"] == "2"
    assert len(result["sourceData"]["features"]) == 2
    assert result["sourceData"]["features"][1]["geometry"]["coordinates"] == [[121.15, 23.48], [121.2, 23.5]]
    assert all(feature["properties"]["candidate_only"] for feature in result["sourceData"]["features"])
    assert all(not feature["properties"]["runtime_safety_truth"] for feature in result["sourceData"]["features"])


def test_single_point_starts_at_final_camera_without_post_load_animation() -> None:
    result = _run("""
const point = makeFeature("point-a", [121.2, 23.5], "Point");
const pending = api.createRenderer(options(), api.createEvidenceFeatureCollection([point]));
const initial = renderer.map.initialCamera; load(); await pending;
console.log(JSON.stringify({initial, changes, statuses})); renderer.destroy();
""")
    assert result["initial"] == {"center": [121.2, 23.5], "zoom": 16, "bounds": None}
    assert result["changes"] == []
    assert result["statuses"][-1] == {"state": "ready", "mapLoaded": True}


def test_empty_evidence_retains_original_default_camera() -> None:
    result = _run("""
const pending = api.createRenderer(options()); const initial = renderer.map.initialCamera;
load(); await pending; console.log(JSON.stringify({initial, changes, statuses})); renderer.destroy();
""")
    assert result["initial"] == {"center": [0, 0], "zoom": 1, "bounds": None}
    assert result["changes"] == []
    assert result["statuses"][-1] == {"state": "ready", "mapLoaded": True}


def test_initial_view_respects_native_camera_cap() -> None:
    result = _run("""
const point = makeFeature("point-a", [121.2, 23.5], "Point");
const rasterLayers = [{layer_id: "rudy-twmap", source_id: "happyman_rudy_twmap",
  tiles: ["/tiles/{z}/{x}/{y}.png?native=1&exact=1"], minzoom: 5, maxzoom: 15, tile_size: 256}];
const pending = api.createRenderer(options({rasterLayers}), api.createEvidenceFeatureCollection([point]));
const initial = renderer.map.initialCamera, maximum = renderer.map.options.maxZoom;
load(); await pending; console.log(JSON.stringify({initial, maximum, changes})); renderer.destroy();
""")
    assert result["initial"]["zoom"] == result["maximum"] == 14
    assert result["changes"] == []


def test_source_ready_without_map_load_still_expires_at_unchanged_deadline() -> None:
    result = _run("""
const pending = api.createRenderer(options(), collection).catch(error => error.message);
renderer.map.styleReady = renderer.map.tilesReady = true;
renderer.map.fire("sourcedata", {sourceId: api.sourceId, isSourceLoaded: true});
const before = statuses.slice(); expire(); const outcome = await pending;
console.log(JSON.stringify({outcome, before, statuses, receipt: JSON.parse(host.dataset.maplibreInitReceipt)}));
""")
    assert result["outcome"] == "maplibre_initialization_timeout"
    assert result["receipt"]["timeoutMs"] == result["receipt"]["elapsedMs"] == 20000
    assert result["receipt"]["styleReady"] is True
    assert result["receipt"]["allTilesLoaded"] is True
    assert result["receipt"]["mapLoaded"] is False
    assert not any(status["state"] == "ready" for status in result["statuses"])


def test_feature_refresh_during_initialization_is_not_overwritten_after_load() -> None:
    result = _run("""
const pending = api.createRenderer(options(), collection);
const replacement = api.createEvidenceFeatureCollection([side]); renderer.setFeatureCollection(replacement);
load(); await pending;
console.log(JSON.stringify({changes, count: renderer.map.source.data.features.length,
  id: renderer.map.source.data.features[0].id, statuses})); renderer.destroy();
""")
    assert [change["kind"] for change in result["changes"]] == ["setData"]
    assert result["count"] == 1
    assert result["id"] == "route:route-b"
    assert result["statuses"][-1] == {"state": "ready", "mapLoaded": True}


def test_destroy_during_initial_view_prevents_late_ready() -> None:
    result = _run("""
const pending = api.createRenderer(options(), collection).catch(error => error.name);
const map = renderer.map; renderer.destroy(); map.ready = true; map.fire("load");
console.log(JSON.stringify({outcome: await pending, statuses, removed: map.removed, timers: timers.size}));
""")
    assert result["outcome"] == "AbortError"
    assert result["removed"] == 1
    assert result["timers"] == 0
    assert not any(status["state"] == "ready" for status in result["statuses"])



def test_repeated_visible_states_do_not_restart_complete_vector_source() -> None:
    result = _run("""
const pending = api.createRenderer(options(), collection); load(); await pending;
for (const id of ["route", "reference-tracks", "rudy-twmap", "route"]) renderer.setLayerVisibility(id, true);
console.log(JSON.stringify({changes, mapLoaded: renderer.map.loaded(), count: renderer.map.source.data.features.length}));
renderer.destroy();
""")
    assert result == {"changes": [], "mapLoaded": True, "count": 2}


def test_genuine_hide_and_show_keep_full_collection_and_idempotent_replays() -> None:
    result = _run("""
const pending = api.createRenderer(options(), collection); load(); await pending; changes = [];
renderer.setLayerVisibility("route", false); const hidden = renderer.map.source.data;
renderer.setLayerVisibility("route", false); const afterRepeatHide = changes.length;
renderer.setLayerVisibility("route", true); const shown = renderer.map.source.data;
renderer.setLayerVisibility("route", true);
console.log(JSON.stringify({changes, afterRepeatHide, hidden, shown})); renderer.destroy();
""")
    assert len(result["changes"]) == 2
    assert result["afterRepeatHide"] == 1
    assert len(result["hidden"]["features"]) == len(result["shown"]["features"]) == 2
    for hidden, shown in zip(result["hidden"]["features"], result["shown"]["features"]):
        assert hidden["geometry"] == shown["geometry"]
        assert hidden["properties"]["_scout_visible"] is False
        assert shown["properties"]["_scout_visible"] is True
        assert hidden["properties"]["candidate_only"] is shown["properties"]["candidate_only"] is True
        assert hidden["properties"]["runtime_safety_truth"] is shown["properties"]["runtime_safety_truth"] is False


def test_hidden_empty_layer_state_is_retained_for_later_source_refresh() -> None:
    result = _run("""
const pending = api.createRenderer(options(), collection); load(); await pending; changes = [];
renderer.setLayerVisibility("checkpoints", false); const emptyLayerChanges = changes.length;
const point = api.createEvidenceFeature({source_id: "cp-a", candidate_only: true, runtime_safety_truth: false},
  {layerId: "checkpoints", geometry: {type: "Point", coordinates: [121.1, 23.45]}});
renderer.setFeatureCollection(api.createEvidenceFeatureCollection([route, side, point]));
console.log(JSON.stringify({emptyLayerChanges, changes, hiddenLayers: host.dataset.maplibreHiddenLayers,
  features: renderer.map.source.data.features})); renderer.destroy();
""")
    assert result["emptyLayerChanges"] == 0
    assert len(result["changes"]) == 1
    assert result["hiddenLayers"] == "checkpoints"
    assert len(result["features"]) == 3
    assert result["features"][-1]["properties"]["_scout_visible"] is False
    assert result["features"][0]["properties"]["_scout_visible"] is True


def test_explicit_source_change_always_replaces_complete_data() -> None:
    result = _run("""
const pending = api.createRenderer(options(), collection); load(); await pending; changes = [];
const revised = {...route, properties: {...route.properties, display_label: "revised source description"}};
renderer.setFeatureCollection(api.createEvidenceFeatureCollection([revised, side]));
console.log(JSON.stringify({changes, features: renderer.map.source.data.features})); renderer.destroy();
""")
    assert len(result["changes"]) == 1
    assert len(result["features"]) == 2
    assert result["features"][0]["properties"]["display_label"] == "revised source description"



def test_initial_fit_preserves_duplicate_and_property_only_id_resolution() -> None:
    result = _run("""
const samples = [
  {name: "duplicate", features: [{...route, id: side.id}, side]},
  {name: "propertyOnly", features: [{...route, id: undefined,
    properties: {...route.properties, feature_id: "legacy-property-id"}}]},
];
const results = [];
for (const sample of samples) {
  changes = [];
  const pending = api.createRenderer(options(), api.createEvidenceFeatureCollection(sample.features));
  load(); await pending;
  const legacyFit = changes.filter(change => change.kind === "fitBounds").at(-1);
  results.push({name: sample.name, fitBounds: legacyFit?.bounds ?? renderer.map.options.bounds ?? null,
    sourceCount: renderer.map.source.data.features.length, center: renderer.map.options.center ?? null});
  renderer.destroy();
}
console.log(JSON.stringify({results}));
""")
    duplicate, property_only = result["results"]
    assert duplicate["fitBounds"] == [[121.05, 23.41], [121.16, 23.49]]
    assert duplicate["sourceCount"] == 2, "Identity resolution must not discard source features"
    assert property_only["fitBounds"] is None
    assert property_only["center"] == [0, 0]
    assert property_only["sourceCount"] == 1
