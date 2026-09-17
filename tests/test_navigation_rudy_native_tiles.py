"""Navigation uses the shared native transport, including pitched mixed-LOD views."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "docs/admin/scout-dashboard-v0.1.html"
ADAPTER = ROOT / "docs/admin/scout-maplibre-evidence.js"


def _run(probe: str, modes: tuple[str, ...] = ("2d",)) -> dict:
    node = shutil.which("node")
    assert node, "Node is required for the Navigation native-tile regression gate"
    html = PAGE.read_text(encoding="utf-8")
    helpers = html.split("    function navigationTerrainRudyTileTemplate(", 1)[1].split(
        "    function qgisTerrainRouteDraftFeatureCollection", 1
    )[0]
    initializer = html.split("    async function initializeNavigationTerrainMapLibre()", 1)[1].split(
        "    function navigationTerrainSelectedHierarchyEdge", 1
    )[0]
    program = r"""
global.window = globalThis;
global.location = {origin: "http://scout.test", search: ""};
require(process.argv[1]);
const api = ScoutMapLibreEvidence;
const protocols = new Map(), requests = [];
const empty = () => {};
const element = () => ({dataset: {}, style: {}, handlers: {}, disabled: false,
  addEventListener(name, fn) {this.handlers[name] = fn;},
  setAttribute(name, value) {this[name] = value;}, focus: empty,
  click() {if (!this.disabled) this.handlers.click?.();},
});
const hosts = MODES.map(mode => {
  const status = element(), updates = element(), retry = element(), native = element(), fit = element();
  const host = element(); host.isConnected = true;
  host.dataset = {navigationMaplibreMap: mode, navigationEvidenceDomain: "observed"};
  host.parts = {status, updates, retry, native, fit};
  host.parentElement = {querySelector(selector) {
    if (selector.includes("data-navigation-maplibre-state")) return status;
    if (selector.includes("data-map-rudy-updates")) return updates;
    if (selector.includes("data-map-rudy-retry")) return retry;
    if (selector.includes("data-navigation-rudy-status")) return native;
    return fit;
  }};
  return host;
});
global.document = {querySelectorAll: () => hosts};
const state = {route: "outdoor-navigation"};
const navigationTerrainMapLibreRuntime = {generation: 1, maps: [], pendingInitializations: new Set(),
  initializationStarted: 0, initializationSettled: 0};
const NAVIGATION_RUDY_TILE_SOURCE = {cacheLayerId: "imagery", sourceId: "happyman_rudy_twmap", minZoom: 5, maxZoom: 20};
const projectId = () => "dongqing_batongguan_historic_trail_newImport";
const snapshot = {terrain_raster_dem: {maxzoom: 13, minzoom: 11, tile_count: 4, source_cell_resolution_m: 20},
  route_samples: {points: [{elevation_m: 2000}]}};
const navigationTerrainSnapshot = () => snapshot;
const navigationTerrainRouteDemCoverageText = () => "DEM coverage";
const navigationTerrainInterpolationText = () => "source resolution unchanged";
const navigationTerrainDemReady = () => true;
const navigationTerrainMapLibreFeatureCollection = () => ({features: []});
const navigationTerrainMapLibreVisibilitySummary = () => ({});
const navigationTerrainMapLibreLensSummary = () => ({qgis_count: 0, title_text: "candidate", status_text: "candidate"});
const navigationTerrainRouteHypothesis = () => null;
const navigationTerrainRouteHypothesisDisplayLabel = () => "candidate";
const navigationTerrainMapLibreCameraScope = () => "scope";
const navigationTerrainMapLibreStoredCamera = () => null;
const navigationTerrainCameraMinimumZoom = () => 5;
const navigationTerrainFitBounds = () => [[121, 23], [121.01, 23.01]];
const navigationTerrainMapLibreBounds = navigationTerrainFitBounds;
const navigationTerrainMapLibreLocalDetailCenter = () => [121, 23];
const configureNavigationTerrainMapLibreKeyboardSurface = (_map, host) => host;
const configureNavigationTerrainEvidenceControls = () => {};
const addNavigationTerrainRouteAnnotations = () => [];
const navigationTerrainVisualPreset = () => "rudy";
const navigationTerrainRudyOpacity = () => 1;
const qgisTerrainRouteSelectionTarget = () => null;
const fitNavigationTerrainMapLibre = empty;
const synchronizeNavigationTerrainMapLibre = empty;
const rememberNavigationTerrainMapLibreCamera = empty;
const navigationTerrainOptionalOverlayError = event => String(event.sourceId).startsWith("optional-");
const escapeHtml = value => String(value);
const valueOrDash = value => value ?? "—";
const formatInteger = value => String(value);
const asArray = value => Array.isArray(value) ? value : [];
const cssEscape = value => value;
let hideRudyAtCreation = false;
const navigationTerrainMapLibreStyle = () => ({version: 8, sources: {"scout-rudy-tw": {}},
  layers: [{id: "scout-rudy-tw", layout: {visibility: hideRudyAtCreation ? "none" : "visible"}}]});
class FakeMap {
  constructor(options) {
    this.options = options; this.style = options.style; this.host = options.container;
    this.handlers = new Map(); this.settled = false; this.zoom = 19;
    this.terrain = options.pitch ? {decoded: true} : null;
    this.scrollZoom = this.doubleClickZoom = {disable: empty};
    this.canvas = element();
    this.ideals = options.pitch
      ? [{canonical: {z: 18, x: 219250, y: 113500}}, {canonical: {z: 20, x: 877000, y: 454000}}]
      : [{canonical: {z: 20, x: 877000, y: 454000}}, {canonical: {z: 20, x: 877001, y: 454000}}];
    const source = this.style.sources["scout-rudy-tw"];
    source.roundZoom = true;
    source.setTiles = tiles => {source.tiles = tiles; this.settled = false;};
  }
  on(name, fn) {if (!this.handlers.has(name)) this.handlers.set(name, []); this.handlers.get(name).push(fn);}
  once(name, fn) {const run = (...args) => {this.handlers.set(name, this.handlers.get(name).filter(x => x !== run)); fn(...args);}; this.on(name, run);}
  fire(name, value = {}) {for (const fn of [...(this.handlers.get(name) || [])]) fn(value);}
  getSource(id) {return this.style.sources[id];}
  coveringTiles(options) {this.coverageOptions = options; return this.ideals;}
  getZoom() {return this.zoom;}
  getMaxZoom() {return this.options.maxZoom;}
  setMaxZoom(value) {this.options.maxZoom = value; this.zoom = Math.min(this.zoom, value);}
  getCenter() {return {lng: 121, lat: 23};}
  getPitch() {return this.options.pitch;}
  getBearing() {return this.options.bearing;}
  getCanvas() {return this.canvas;}
  addControl() {}
  areTilesLoaded() {return this.settled;}
  isSourceLoaded() {return this.settled;}
  queryTerrainElevation() {return 2000;}
}
const maplibregl = {Map: FakeMap, NavigationControl: class {}, AttributionControl: class {},
  addProtocol: (name, fn) => protocols.set(name, fn), removeProtocol: name => protocols.delete(name), getVersion: () => "6.2.0"};
const loadNavigationTerrainMapLibre = async () => maplibregl;
global.fetch = async (url, options) => {
  requests.push({url, options});
  return {status: responseStatus, ok: responseStatus === 200, headers: new Headers(),
    arrayBuffer: async () => new Uint8Array([137, 80, 78, 71]).buffer};
};
let responseStatus = 200;
const load = async (entry, tile, status = 200) => {
  responseStatus = status;
  const template = entry.map.getSource("scout-rudy-tw").tiles[0];
  const url = template.replaceAll("{z}", tile.z).replaceAll("{x}", tile.x).replaceAll("{y}", tile.y);
  try {await protocols.get(url.split(":")[0])({url}, new AbortController());} catch (_) {}
};
const settle = entry => {entry.map.settled = true; entry.map.fire("sourcedata", {sourceId: "scout-rudy-tw", isSourceLoaded: true}); entry.map.fire("idle");};
const run = async () => {
  await initializeNavigationTerrainMapLibre();
  for (const entry of navigationTerrainMapLibreRuntime.maps) entry.map.fire("load");
};
""".replace("MODES", json.dumps(modes))
    program += "\nfunction navigationTerrainRudyTileTemplate(" + helpers
    program += "\nasync function initializeNavigationTerrainMapLibre()" + initializer
    program += "\n(async () => {\n" + probe + "\n})().catch(error => {console.error(error); process.exit(1);});"
    result = subprocess.run([node, "-e", program, str(ADAPTER)], cwd=ROOT, text=True, capture_output=True, check=True)
    return json.loads(result.stdout)


@pytest.mark.parametrize("mode", ["2d", "3d"])
def test_navigation_ready_requires_every_current_native_tile(mode: str) -> None:
    result = _run("""
await run(); const entry = navigationTerrainMapLibreRuntime.maps[0];
const initial = {...entry.host.dataset};
const tiles = navigationTerrainRudyDiagnosticView(entry).tiles;
await load(entry, tiles[0]); settle(entry);
const missing = {...entry.host.dataset};
await load(entry, tiles[1]); settle(entry);
console.log(JSON.stringify({initial, missing, full: {...entry.host.dataset}, label: entry.host.parts.native.textContent,
  urls: requests.map(r => r.url), maximum: entry.map.options.maxZoom, terrain: entry.map.coverageOptions.terrain,
  expected: navigationTerrainRudyDiagnosticView(entry)}));
""", (mode,))
    assert result["initial"]["navigationMaplibreStatus"] != "ready"
    assert result["missing"]["maplibreRasterState"] == "degraded"
    assert result["missing"]["navigationMaplibreStatus"] != "ready"
    assert result["missing"]["maplibreRasterUnverifiedCount"] == "1"
    assert result["full"]["navigationMaplibreStatus"] == "ready"
    assert result["full"]["maplibreRasterState"] == "available"
    assert result["full"]["maplibreRasterVerifiedNativeZoom"] == "20"
    assert result["full"]["maplibreRasterSuccessCount"] == "2"
    assert result["expected"]["coverageBasis"] == "maplibre-covering-tiles"
    assert result["maximum"] == 19
    assert all("native=1" in url and "exact=1" in url and "refresh=1" not in url for url in result["urls"])
    assert result["full"]["maplibreRasterNativeZooms"] == ("18,20" if mode == "3d" else "20")
    if mode == "3d":
        assert result["terrain"] == {"decoded": True}
        assert "Z18 / Z20" in result["label"]


def test_parent_fallback_and_http_200_elsewhere_do_not_pass_navigation() -> None:
    result = _run("""
await run(); const entry = navigationTerrainMapLibreRuntime.maps[0];
await load(entry, {z: 19, x: 438500, y: 227000});
await load(entry, {z: 20, x: 877005, y: 454005});
await load(entry, {z: 20, x: 877000, y: 454000}, 404); settle(entry);
console.log(JSON.stringify({...entry.host.dataset}));
""")
    assert result["maplibreRasterState"] == "degraded"
    assert result["maplibreRasterSuccessCount"] == "0"
    assert result["maplibreRasterErrorCount"] == "1"
    assert result["maplibreRasterVerifiedNativeZoom"] == ""
    assert result["navigationMaplibreStatus"] != "ready"


def test_navigation_controls_switch_exact_cache_mode_and_retry_without_camera_change() -> None:
    result = _run("""
await run(); const entry = navigationTerrainMapLibreRuntime.maps[0];
entry.host.parts.updates.click();
const offline = entry.rudyLayer.tiles[0];
entry.host.parts.retry.click();
const retry = entry.rudyLayer.tiles[0];
window.location.search = "?diagnosticMapProbe=1&diagnosticNativeTiles=1";
entry.host.parts.retry.click();
console.log(JSON.stringify({offline, retry, diagnostic: entry.rudyLayer.tiles[0], dataset: entry.host.dataset,
  zoom: entry.map.getZoom(), button: entry.host.parts.updates["aria-pressed"]}));
""")
    assert "cache_only=1" in result["offline"] and "native=1" not in result["offline"]
    assert "native=1" in result["retry"] and "refresh=1" in result["retry"]
    assert "native=1" in result["diagnostic"] and "refresh=1" not in result["diagnostic"]
    assert all("exact=1" in result[key] for key in ("offline", "retry", "diagnostic"))
    assert result["zoom"] == 19
    assert result["button"] == "true"
    assert result["dataset"]["maplibreRasterVerifiedNativeZoom"] == ""


@pytest.mark.parametrize("native_authorized", [False, True])
def test_diagnostic_transport_permission_applies_before_first_request_and_to_controls(native_authorized: bool) -> None:
    search = "?diagnosticMapProbe=1" + ("&diagnosticNativeTiles=1" if native_authorized else "")
    result = _run("window.location.search = " + json.dumps(search) + ";\n" + """
await run();
const rows = [];
for (const entry of navigationTerrainMapLibreRuntime.maps) {
  const initial = {template: entry.rudyLayer.tiles[0], updates: entry.host.dataset.dashboardTileUpdates,
    pressed: entry.host.parts.updates["aria-pressed"]};
  await load(entry, navigationTerrainRudyDiagnosticView(entry).tiles[0]);
  entry.host.parts.updates.click(); entry.host.parts.retry.click();
  await load(entry, navigationTerrainRudyDiagnosticView(entry).tiles[0]);
  rows.push({initial, retry: entry.rudyLayer.tiles[0], updates: entry.host.dataset.dashboardTileUpdates});
}
console.log(JSON.stringify({rows, requests: requests.map(request => request.url)}));
""", ("2d", "3d"))
    for row in result["rows"]:
        assert row["initial"]["updates"] == row["updates"] == ("auto" if native_authorized else "offline")
        assert row["initial"]["pressed"] == str(native_authorized).lower()
        for template in (row["initial"]["template"], row["retry"]):
            assert ("native=1" in template) is native_authorized
            assert ("cache_only=1" in template) is not native_authorized
            assert "refresh=1" not in template
    assert all(("native=1" in url) is native_authorized and "exact=1" in url and "refresh=1" not in url
               for url in result["requests"])


def test_navigation_pan_invalidates_old_cohort_and_recovers_only_new_tiles() -> None:
    result = _run("""
await run(); const entry = navigationTerrainMapLibreRuntime.maps[0];
for (const tile of navigationTerrainRudyDiagnosticView(entry).tiles) await load(entry, tile);
settle(entry);
entry.map.ideals = [{canonical: {z: 20, x: 877100, y: 454100}}];
entry.map.fire("move");
const moved = {...entry.host.dataset};
await load(entry, entry.map.ideals[0].canonical); settle(entry);
console.log(JSON.stringify({moved, recovered: {...entry.host.dataset}}));
""")
    assert result["moved"]["maplibreRasterVerifiedNativeZoom"] == ""
    assert result["moved"]["maplibreRasterSuccessCount"] == "0"
    assert result["moved"]["navigationMaplibreStatus"] != "ready"
    assert result["recovered"]["maplibreRasterState"] == "available"
    assert result["recovered"]["maplibreRasterSuccessCount"] == "1"


def test_covering_tiles_deduplicates_wraps_and_respects_source_coverage() -> None:
    result = _run("""
await run(); const entry = navigationTerrainMapLibreRuntime.maps[0];
entry.map.ideals = [{canonical: {z: 20, x: 877000, y: 454000}, wrap: 0},
  {canonical: {z: 20, x: 877000, y: 454000}, wrap: 1},
  {canonical: {z: 18, x: 219250, y: 113500}}];
entry.map.getSource("scout-rudy-tw").hasTile = tile => tile.canonical.z === 20;
const coverage = api.rasterTileCoverage(entry.rudyLayer, entry.map);
entry.map.coveringTiles = () => {throw Error("style removed");};
console.log(JSON.stringify({coverage, failure: api.rasterTileCoverage(entry.rudyLayer, entry.map)}));
""")
    assert result["coverage"]["count"] == 1
    assert result["coverage"]["native_zooms"] == [20]
    assert result["failure"] is None


def test_hidden_basemap_does_not_claim_native_tiles_loaded() -> None:
    result = _run("""
hideRudyAtCreation = true;
await run(); const entry = navigationTerrainMapLibreRuntime.maps[0]; settle(entry);
console.log(JSON.stringify({dataset: entry.host.dataset, label: entry.host.parts.native.textContent}));
""")
    assert result["dataset"]["maplibreRasterState"] == "hidden"
    assert result["dataset"]["maplibreRasterVerifiedNativeZoom"] == ""
    assert result["dataset"]["maplibreRasterSuccessCount"] == "0"
    assert result["label"] == "Rudy 圖層已隱藏"
