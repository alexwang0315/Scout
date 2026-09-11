import json
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "docs/admin/scout-maplibre-evidence.js"


def _run(probe: str) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for MapLibre transport tests")
    program = r"""
global.window = globalThis;
global.location = {origin: "http://scout.test"};
require(process.argv[1]);
const api = ScoutMapLibreEvidence;
const protocols = new Map(), requests = [], rasterEvents = [];
const container = {dataset: {}};
const controller = () => new AbortController();
const tileLat = (y, z) => Math.atan(Math.sinh(Math.PI * (1 - 2 * y / (2 ** z)))) * 180 / Math.PI;
const tileLon = (x, z) => x / (2 ** z) * 360 - 180;
class FakeMap {
  constructor(options) {
    this.options = options;
    this.style = options.style;
    this.handlers = new Map();
    this.zoom = 19;
    this.view = {z: 20, west: 877000.1, east: 877001.9, north: 454000.1, south: 454001.9};
    this.settled = false;
  }
  loaded() { return true; }
  on(kind, ...args) {
    if (!this.handlers.has(kind)) this.handlers.set(kind, []);
    this.handlers.get(kind).push(args.at(-1));
  }
  fire(kind, event = {}) { (this.handlers.get(kind) || []).forEach(callback => callback(event)); }
  getSource(id) { return this.style.sources[id]; }
  getLayer(id) { return this.style.layers.find(layer => layer.id === id); }
  getStyle() { return this.style; }
  addSource(id, source) { this.style.sources[id] = source; }
  removeSource(id) { delete this.style.sources[id]; }
  removeLayer(id) { this.style.layers = this.style.layers.filter(layer => layer.id !== id); }
  addLayer(layer, before) {
    const index = this.style.layers.findIndex(candidate => candidate.id === before);
    if (index < 0) this.style.layers.push(layer); else this.style.layers.splice(index, 0, layer);
  }
  setLayoutProperty(id, name, value) { this.getLayer(id).layout[name] = value; }
  getZoom() { return this.zoom; }
  getCenter() { return {lng: 121, lat: 24}; }
  getBounds() {
    const v = this.view;
    return {getWest: () => tileLon(v.west, v.z), getEast: () => tileLon(v.east, v.z),
      getNorth: () => tileLat(v.north, v.z), getSouth: () => tileLat(v.south, v.z)};
  }
  isSourceLoaded() { return this.settled; }
  remove() { this.removed = true; }
}
const maplibregl = {Map: FakeMap,
  addProtocol: (name, handler) => protocols.set(name, handler),
  removeProtocol: name => protocols.delete(name)};
global.fetch = (url, options) => new Promise((resolve, reject) => {
  const request = {url, options,
    respond: status => resolve({status, ok: status >= 200 && status < 300,
      headers: new Headers({"Cache-Control": "public, max-age=120"}),
      arrayBuffer: async () => new Uint8Array([137, 80, 78, 71]).buffer}),
    reject};
  requests.push(request);
  options.signal.addEventListener("abort", () => reject(Object.assign(new Error("cancelled"), {name: "AbortError"})), {once: true});
});
const definition = (extra = {}) => ({layer_id: "rudy-twmap", source_id: "happyman_rudy_twmap",
  tiles: ["/admin/tiles/imagery/demo/rudy-twmap/{z}/{x}/{y}.png?cache_only=1&exact=1"],
  minzoom: 5, maxzoom: 20, visible: true, ...extra});
const settle = renderer => {
  renderer.map.settled = true;
  renderer.map.fire("sourcedata", {sourceId: "scout-raster-rudy-twmap", isSourceLoaded: true});
};
const snap = renderer => ({state: {...renderer.rasterLayerStates.get("rudy-twmap")},
  dataset: {...container.dataset}, requests: requests.length});
const tile = (renderer, x, y, z = 20, options = {}) => {
  const template = options.template || renderer.map.getSource("scout-raster-rudy-twmap").tiles[0];
  const url = template.replaceAll("{z}", String(z)).replaceAll("{x}", String(x)).replaceAll("{y}", String(y));
  const abort = controller();
  const pending = protocols.get(url.split(":")[0])({url}, abort);
  pending.catch(() => {});
  return {pending, abort, request: requests.at(-1), url};
};
const loadView = async renderer => {
  for (const x of [877000, 877001]) for (const y of [454000, 454001]) {
    const result = tile(renderer, x, y);
    result.request.respond(200);
    await result.pending;
  }
};
(async () => {
  const renderer = await api.createRenderer({maplibregl, container, rasterLayers: [definition()],
    onRasterStatus: (next, states) => rasterEvents.push({next, states})});
""" + probe + "\n})().catch(error => {console.error(error); process.exitCode = 1;});"
    completed = subprocess.run(
        [node, "-e", program, str(SCRIPT)], text=True, capture_output=True, cwd=ROOT, timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def test_http_404_is_visible_without_any_maplibre_error_event() -> None:
    result = _run("""
const failed = tile(renderer, 877000, 454000);
failed.request.respond(404);
await failed.pending.catch(() => {});
settle(renderer);
console.log(JSON.stringify(snap(renderer)));
""")
    assert result["state"]["state"] == "degraded"
    assert result["state"]["reason"] == "native_tile_http_error"
    assert result["state"]["error_count"] == 1
    assert result["state"]["last_http_status"] == 404
    assert result["state"]["required_count"] == 4
    assert result["dataset"]["maplibreRasterVerifiedNativeZoom"] == ""
    assert result["dataset"]["maplibreRasterState"] == "degraded"


def test_source_loaded_does_not_certify_unobserved_native_tiles() -> None:
    result = _run("settle(renderer); console.log(JSON.stringify(snap(renderer)));")
    assert result["state"]["state"] == "degraded"
    assert result["state"]["reason"] == "native_tiles_unverified"
    assert result["state"]["unverified_count"] == 4
    assert result["state"]["verified_native_zoom"] is None


def test_all_native_http_successes_still_wait_for_source_settled() -> None:
    result = _run("""
await loadView(renderer);
const before = snap(renderer);
settle(renderer);
console.log(JSON.stringify({before, after: snap(renderer), credentials: requests.map(request => request.options.credentials),
  redirects: requests.map(request => request.options.redirect), urls: requests.map(request => request.url)}));
""")
    assert result["before"]["state"]["state"] == "loading"
    assert result["after"]["state"]["state"] == "available"
    assert result["after"]["state"]["verified_native_zoom"] == 20
    assert result["after"]["dataset"]["maplibreRasterVerifiedNativeZoom"] == "20"
    assert result["after"]["dataset"]["maplibreRasterSuccessCount"] == "4"
    assert result["credentials"] == ["same-origin"] * 4
    assert result["redirects"] == ["error"] * 4
    assert all(url.startswith("http://scout.test/admin/tiles/") and "cache_only=1&exact=1" in url for url in result["urls"])


def test_parent_tile_success_does_not_hide_missing_native_detail() -> None:
    result = _run("""
const failed = tile(renderer, 877000, 454000);
failed.request.respond(404);
await failed.pending.catch(() => {});
const parent = tile(renderer, 438500, 227000, 19);
parent.request.respond(200);
await parent.pending;
settle(renderer);
console.log(JSON.stringify(snap(renderer)));
""")
    assert result["state"]["native_zoom"] == 20
    assert result["state"]["success_count"] == 0
    assert result["state"]["error_count"] == 1
    assert result["state"]["state"] == "degraded"


@pytest.mark.parametrize("older,newer,expected", [(200, 404, "degraded"), (404, 200, "available")])
def test_late_request_cannot_override_a_newer_attempt(older: int, newer: int, expected: str) -> None:
    result = _run(f"""
await loadView(renderer);
const old = tile(renderer, 877000, 454000);
const current = tile(renderer, 877000, 454000);
current.request.respond({newer});
await current.pending.catch(() => {{}});
old.request.respond({older});
await old.pending.catch(() => {{}});
settle(renderer);
console.log(JSON.stringify(snap(renderer)));
""")
    assert result["state"]["state"] == expected
    assert result["state"]["error_count"] == int(newer == 404)


def test_pan_filters_old_errors_and_cached_successes_can_restore_availability() -> None:
    result = _run("""
await loadView(renderer);
renderer.map.view.west += 2;
renderer.map.view.east += 2;
renderer.map.fire("move");
const failed = tile(renderer, 877002, 454000);
failed.request.respond(404);
await failed.pending.catch(() => {});
settle(renderer);
const failedView = snap(renderer);
renderer.map.view.west -= 2;
renderer.map.view.east -= 2;
renderer.map.fire("moveend");
console.log(JSON.stringify({failedView, restored: snap(renderer)}));
""")
    assert result["failedView"]["state"]["error_count"] == 1
    assert result["restored"]["state"]["state"] == "available"
    assert result["restored"]["state"]["error_count"] == 0


def test_zooming_out_does_not_keep_an_unrelated_higher_zoom_error() -> None:
    result = _run("""
const failed = tile(renderer, 877000, 454000);
failed.request.respond(404);
await failed.pending.catch(() => {});
const parent = tile(renderer, 438500, 227000, 19);
parent.request.respond(200);
await parent.pending;
renderer.map.zoom = 18;
settle(renderer);
renderer.map.fire("moveend");
console.log(JSON.stringify(snap(renderer)));
""")
    assert result["state"]["native_zoom"] == 19
    assert result["state"]["required_count"] == 1
    assert result["state"]["error_count"] == 0
    assert result["state"]["state"] == "available"


def test_abort_is_not_a_tile_failure_and_preserves_previous_verified_data() -> None:
    result = _run("""
await loadView(renderer);
const retry = tile(renderer, 877000, 454000);
retry.abort.abort();
await retry.pending.catch(() => {});
settle(renderer);
console.log(JSON.stringify(snap(renderer)));
""")
    assert result["state"]["state"] == "available"
    assert result["state"]["error_count"] == 0
    assert result["state"]["pending_count"] == 0


def test_source_switch_aborts_old_requests_and_rejects_old_protocol_urls() -> None:
    result = _run("""
const oldTemplate = renderer.map.getSource("scout-raster-rudy-twmap").tiles[0];
const old = tile(renderer, 877000, 454000);
renderer.setRasterLayers([definition({tiles: ["/admin/tiles/imagery/other/rudy-twmap/{z}/{x}/{y}.png?native=1&exact=1"]})]);
await old.pending.catch(() => {});
const oldUrl = tile(renderer, 877000, 454000, 20, {template: oldTemplate});
const rejected = await oldUrl.pending.then(() => false, error => error.name);
await loadView(renderer);
settle(renderer);
console.log(JSON.stringify({oldAborted: old.abort.signal.aborted, rejected, final: snap(renderer), urls: requests.map(request => request.url)}));
""")
    assert result["oldAborted"] is True
    assert result["rejected"] == "AbortError"
    assert result["final"]["state"]["state"] == "available"
    assert result["final"]["state"]["transport_revision"] == 2
    assert len(result["urls"]) == 5
    assert all("/other/" in url for url in result["urls"][1:])


def test_hidden_rudy_does_not_pollute_host_summary_and_can_be_restored() -> None:
    result = _run("""
await loadView(renderer);
settle(renderer);
renderer.setLayerVisibility("rudy-twmap", false);
const hidden = snap(renderer);
renderer.setLayerVisibility("rudy-twmap", true);
console.log(JSON.stringify({hidden, visible: snap(renderer)}));
""")
    assert result["hidden"]["state"]["state"] == "hidden"
    assert result["hidden"]["dataset"]["maplibreRasterNativeZoom"] == ""
    assert result["hidden"]["dataset"]["maplibreRasterRequiredCount"] == "0"
    assert result["visible"]["state"]["state"] == "available"


def test_explicit_remote_layers_are_not_wrapped_and_do_not_change_layer_order() -> None:
    result = _run("""
const layers = [definition(), definition({layer_id: "remote", source_id: "remote-source",
  network_scope: "explicit_remote", tiles: ["https://tiles.example/{z}/{x}/{y}.png"]})];
const expected = api.createEvidenceStyle(api.createEvidenceFeatureCollection(), {rasterLayers: layers}).layers.map(layer => layer.id);
const second = await api.createRenderer({maplibregl, container: {dataset: {}}, rasterLayers: layers});
console.log(JSON.stringify({expected, actual: second.map.getStyle().layers.map(layer => layer.id),
  remote: second.map.getSource("scout-raster-remote").tiles, requests: requests.length,
  boundary: second.rasterLayers.map(layer => [layer.candidate_only, layer.runtime_safety_truth, layer.operational])}));
""")
    assert result["actual"] == result["expected"]
    assert result["remote"] == ["https://tiles.example/{z}/{x}/{y}.png"]
    assert result["requests"] == 0
    assert result["boundary"] == [[True, False, False], [True, False, False]]


def test_forged_protocol_requests_cannot_introduce_a_new_fetch_url() -> None:
    result = _run("""
const template = renderer.map.getSource("scout-raster-rudy-twmap").tiles[0];
const url = template.replace("/0/{z}/{x}/{y}", "/99/20/877000/454000");
const handler = protocols.get(url.split(":")[0]);
const error = await handler({url}, controller()).then(() => null, error => error.message);
console.log(JSON.stringify({error, requests: requests.length}));
""")
    assert result == {"error": "invalid_raster_protocol_tile", "requests": 0}


def test_destroy_removes_protocol_aborts_requests_and_ignores_late_events() -> None:
    result = _run("""
const pending = tile(renderer, 877000, 454000);
const map = renderer.map;
renderer.destroy();
const afterDestroy = rasterEvents.length;
await pending.pending.catch(() => {});
map.fire("moveend");
map.fire("sourcedata", {sourceId: "scout-raster-rudy-twmap", isSourceLoaded: true});
map.fire("error", {sourceId: "scout-raster-rudy-twmap", error: new Error("late failure")});
console.log(JSON.stringify({aborted: pending.abort.signal.aborted, protocols: protocols.size,
  removed: map.removed, afterDestroy, finalEvents: rasterEvents.length, transport: container.dataset.maplibreRasterTransport}));
""")
    assert result["aborted"] is True
    assert result["protocols"] == 0
    assert result["removed"] is True
    assert result["afterDestroy"] == result["finalEvents"]
    assert result["transport"] == "destroyed"


def test_concurrent_renderers_have_independent_protocols_and_cleanup() -> None:
    result = _run("""
const secondContainer = {dataset: {}};
const second = await api.createRenderer({maplibregl, container: secondContainer, rasterLayers: [definition()]});
const firstProtocol = renderer.map.getSource("scout-raster-rudy-twmap").tiles[0].split(":")[0];
const secondProtocol = second.map.getSource("scout-raster-rudy-twmap").tiles[0].split(":")[0];
renderer.destroy();
await loadView(second);
settle(second);
console.log(JSON.stringify({distinct: firstProtocol !== secondProtocol, protocols: protocols.size,
  firstRemoved: !protocols.has(firstProtocol), secondPresent: protocols.has(secondProtocol),
  secondState: second.rasterLayerStates.get("rudy-twmap").state}));
""")
    assert result == {"distinct": True, "protocols": 1, "firstRemoved": True,
                      "secondPresent": True, "secondState": "available"}


def test_failed_map_initialization_removes_its_registered_protocol() -> None:
    result = _run("""
const before = protocols.size;
const broken = {...maplibregl, Map: class {constructor() {throw new Error("GPU unavailable");}}};
const error = await api.createRenderer({maplibregl: broken, container: {dataset: {}}, rasterLayers: [definition()]})
  .then(() => null, error => error.message);
console.log(JSON.stringify({before, after: protocols.size, error}));
""")
    assert result["before"] == result["after"] == 1
    assert result["error"] == "GPU unavailable"


def test_image_decode_failure_cannot_be_overwritten_by_source_loaded() -> None:
    result = _run("""
await loadView(renderer);
renderer.map.fire("error", {sourceId: "scout-raster-rudy-twmap", error: new Error("invalid image")});
settle(renderer);
const failed = snap(renderer);
const retry = tile(renderer, 877000, 454000);
retry.request.respond(200);
await retry.pending;
settle(renderer);
console.log(JSON.stringify({failed, repaired: snap(renderer)}));
""")
    assert result["failed"]["state"]["state"] == "degraded"
    assert result["failed"]["state"]["reason"] == "tile_decode_failed"
    assert result["failed"]["state"]["verified_native_zoom"] is None
    assert result["repaired"]["state"]["state"] == "available"
