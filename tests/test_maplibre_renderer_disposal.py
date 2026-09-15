"""Explicit destruction of active and pending canonical iframe renderers."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / "docs/admin/scout-maplibre-evidence.js"


def _node(program: str) -> dict:
    node = shutil.which("node")
    assert node, "Node is required for renderer lifecycle regression checks"
    result = subprocess.run([node, "-e", program, str(ADAPTER)], text=True, capture_output=True, check=True)
    return json.loads(result.stdout)


def _factory(probe: str) -> dict:
    program = r"""
global.window = globalThis;
global.location = {origin: "http://scout.test"};
require(process.argv[1]);
let created = 0, removed = 0, candidate = null;
class MapFixture {
  constructor(options) {created++; this.options = options; this.handlers = new Map(); this.ready = false;}
  on(name, ...values) {if (!this.handlers.has(name)) this.handlers.set(name, new Set()); this.handlers.get(name).add(values.at(-1));}
  off(name, fn) {this.handlers.get(name)?.delete(fn);}
  fire(name, value = {}) {for (const fn of [...(this.handlers.get(name) || [])]) fn(value);}
  loaded() {return this.ready;}
  getStyle() {return this.options.style;}
  getSource() {return null;}
  getCanvas() {return {style: {}};}
  getCenter() {return {lng: 121, lat: 23};}
  getZoom() {return 12;}
  remove() {removed++; this.fire("remove");}
}
const container = {dataset: {}};
const options = {maplibregl: {Map: MapFixture}, container, onCreated: value => {candidate = value;}};
"""
    return _node(program + "\n(async () => {\n" + probe + "\n})().catch(e => {console.error(e); process.exit(1);});")


def test_pending_renderer_is_destroyed_once_and_never_activates_late() -> None:
    result = _factory("""
const pending = ScoutMapLibreEvidence.createRenderer(options).catch(error => ({name: error.name, message: error.message}));
const map = candidate.map;
candidate.destroy(); candidate.destroy();
map.fire("load");
console.log(JSON.stringify({outcome: await pending, created, removed, destroyed: candidate.destroyed,
  map: candidate.map, receipt: JSON.parse(container.dataset.maplibreInitReceipt)}));
""")
    assert result["outcome"] == {"name": "AbortError", "message": "maplibre_initialization_cancelled"}
    assert result["created"] == result["removed"] == 1
    assert result["destroyed"] is True and result["map"] is None
    assert result["receipt"]["phase"] == "cancelled"


def test_dispose_between_load_and_continuation_cannot_publish_ready() -> None:
    result = _factory("""
const statuses = [];
const pending = ScoutMapLibreEvidence.createRenderer({...options, onStatus: status => statuses.push(status.state)})
  .catch(error => error.name);
candidate.map.ready = true; candidate.map.fire("load"); candidate.destroy();
console.log(JSON.stringify({outcome: await pending, created, removed, statuses}));
""")
    assert result["outcome"] == "AbortError"
    assert "ready" not in result["statuses"]
    assert result["created"] == result["removed"] == 1


def test_factory_abort_signal_cancels_pending_context() -> None:
    result = _factory("""
const controller = new AbortController();
const pending = ScoutMapLibreEvidence.createRenderer({...options, signal: controller.signal}).catch(error => error.name);
controller.abort();
console.log(JSON.stringify({outcome: await pending, created, removed}));
""")
    assert result == {"outcome": "AbortError", "created": 1, "removed": 1}


def test_already_aborted_factory_does_not_create_a_map() -> None:
    result = _factory("""
const controller = new AbortController(); controller.abort();
const outcome = await ScoutMapLibreEvidence.createRenderer({...options, signal: controller.signal}).catch(error => error.name);
console.log(JSON.stringify({outcome, created, removed}));
""")
    assert result == {"outcome": "AbortError", "created": 0, "removed": 0}


def test_context_removal_survives_ui_cleanup_error() -> None:
    result = _factory("""
const pending = ScoutMapLibreEvidence.createRenderer({...options, onFeatureLeave: () => {throw new Error("fixture cleanup");}})
  .catch(error => error.name);
let destroyError = null;
try {candidate.destroy();} catch(error) {destroyError = error.name;}
candidate.destroy();
console.log(JSON.stringify({outcome: await pending, created, removed, destroyError}));
""")
    assert result["removed"] == result["created"] == 1
    assert result["destroyError"] == "Error"
    assert result["outcome"] == "AbortError"


def test_external_abort_reports_cleanup_error_without_uncaught_event_error() -> None:
    result = _factory("""
const controller = new AbortController();
const pending = ScoutMapLibreEvidence.createRenderer({...options, signal: controller.signal,
  onFeatureLeave: () => {throw new TypeError("fixture cleanup");}}).catch(error => error.name);
controller.abort();
console.log(JSON.stringify({outcome: await pending, created, removed}));
""")
    assert result == {"outcome": "TypeError", "created": 1, "removed": 1}


def _canonical(page: str, probe: str) -> dict:
    pretrip = page == "pretrip"
    path = ROOT / "docs/admin" / ("phase4-pretrip-planning.html" if pretrip else "phase-3-5-runtime-debug.html")
    html = path.read_text(encoding="utf-8")
    prefix = "Pretrip" if pretrip else "Debug"
    functions = "async function dispose" + prefix + "MapRenderer()" + html.split(
        "async function dispose" + prefix + "MapRenderer()", 1
    )[1].split("async function initialize" + prefix + "MapRenderer", 1)[0]
    program = r"""
global.window = globalThis;
const makeElement = () => ({dataset: {}, hidden: false, querySelector: () => null});
const host = makeElement(), shell = makeElement(), svg = makeElement();
global.document = {getElementById: id => id === "mapRendererShell" ? shell : host, querySelectorAll: () => []};
const runtimeMapLibre = host, runtimeMapRendererShell = shell, runtimeMap = svg;
const state = {view: {}, selected: null}, debugPageState = {projection: {}, events: []};
let requests = [], created = 0, removed = 0, fallback = 0, configured = 0, cancelOnDestroy = true;
const empty = () => {};
const features = () => ({features: [{properties: {layer_id: "route"}}]});
const pretripMapLibreFeatureCollection = features, debugMapLibreFeatureCollection = features;
const pretripMapLibreRasterLayers = () => [], debugMapLibreRasterLayers = () => [];
const selectPretripMapLibreFeature = empty, hoverPretripMapLibreFeature = empty, hideHint = empty;
const selectDebugMapLibreFeature = empty, hoverDebugMapLibreFeature = empty, hideMapHoverTooltip = empty;
const updateMapZoomIndicator = empty, updateDebugRudyTileStatus = empty;
const setPretripMapRendererState = empty, setDebugMapRendererState = empty;
const disposeDebugMapEvidenceControls = empty;
const configureDebugMapLibreControls = () => {configured++;};
const disposePretripMapEvidenceControls = empty;
const configurePretripMapEvidenceControls = empty;
const selectedMapEvent = () => null, focusDebugMapLibreForEvent = () => false;
const MAP_RENDERER_PREFERENCE = "maplibre", DEBUG_MAP_RENDERER_PREFERENCE = "maplibre";
const activateSvgMapFallback = () => {fallback++;};
const activateDebugSvgFallback = () => {fallback++;};
window.ScoutMapLibreEvidence = {createRenderer(options) {
  let accept, reject;
  const promise = new Promise((resolve, fail) => {accept = resolve; reject = fail;});
  const renderer = {map: {setMaxZoom: empty}, destroyed: false, resize: empty, fitLayer: empty, setLayerVisibility: empty,
    syncRasterCameraLimits: empty,
    destroy() {if (this.destroyed) return; this.destroyed = true; this.map = null; removed++;
      if (cancelOnDestroy) reject(Object.assign(new Error("cancelled"), {name: "AbortError"}));}};
  created++; options.onCreated?.(renderer);
  requests.push({renderer, resolve() {options.onStatus?.({state: "ready", reason: "fixture"}); accept(renderer);}});
  return promise;
}};
"""
    if pretrip:
        policy = [line for line in html.splitlines() if line.strip().startswith("const MAP_WHEEL_ZOOM_ENABLED = ")]
        assert len(policy) == 1
        program += '\nglobal.location = {search: ""};\n' + policy[0] + "\n"
    program += "\n" + functions + "\nconst current = " + ("state" if pretrip else "debugPageState") + ";"
    program += "\nconst activate = () => activate" + prefix + "MapLibreRenderer({}, {});"
    program += "\nconst dispose = dispose" + prefix + "MapRenderer;"
    return _node(program + "\n(async () => {\n" + probe + "\n})().catch(e => {console.error(e); process.exit(1);});")


@pytest.mark.parametrize("page", ["pretrip", "debug"])
def test_canonical_dispose_cancels_and_awaits_pending_renderer(page: str) -> None:
    result = _canonical(page, """
const activation = activate(); const receipt = await dispose(); const outcome = await activation;
const repeated = await dispose();
console.log(JSON.stringify({receipt, repeated, outcome, created, removed, fallback,
  pending: current.mapLibreInitializations.size, active: current.mapLibreRenderer}));
""")
    assert result["receipt"] == result["repeated"] == {"disposed": True, "activeMaps": 0, "pendingInitializations": 0, "errors": []}
    assert result["outcome"] is None and result["active"] is None
    assert result["created"] == result["removed"] == 1
    assert result["pending"] == result["fallback"] == 0


@pytest.mark.parametrize("page", ["pretrip", "debug"])
def test_canonical_late_result_cannot_reenable_disposed_map(page: str) -> None:
    result = _canonical(page, """
cancelOnDestroy = false;
const activation = activate(); const closing = dispose();
requests[0].resolve(); const receipt = await closing; const outcome = await activation;
console.log(JSON.stringify({receipt, outcome, created, removed, fallback, configured,
  active: current.mapLibreRenderer, rendererState: shell.dataset.mapRendererState || null}));
""")
    assert result["receipt"]["disposed"] is True
    assert result["active"] is None and result["outcome"] is None
    assert result["rendererState"] is None
    assert result["fallback"] == result["configured"] == 0
    assert result["removed"] == 1


@pytest.mark.parametrize("page", ["pretrip", "debug"])
def test_canonical_successful_renderer_is_destroyed_on_close(page: str) -> None:
    result = _canonical(page, """
const activation = activate(); requests[0].resolve(); await activation;
const wasActive = current.mapLibreRenderer === requests[0].renderer;
const receipt = await dispose();
console.log(JSON.stringify({receipt, wasActive, created, removed, fallback}));
""")
    assert result["wasActive"] is True
    assert result["receipt"]["disposed"] is True
    assert result["created"] == result["removed"] == 1
    assert result["fallback"] == 0


@pytest.mark.parametrize("page", ["pretrip", "debug"])
def test_canonical_cleanup_failure_cannot_turn_green_on_repeated_dispose(page: str) -> None:
    result = _canonical(page, """
const activation = activate(); requests[0].resolve(); await activation;
requests[0].renderer.destroy = () => {throw new Error("fixture cleanup failure");};
const first = await dispose(), repeated = await dispose();
console.log(JSON.stringify({first, repeated}));
""")
    assert result["first"] == result["repeated"]
    assert result["first"]["disposed"] is False
    assert result["first"]["activeMaps"] is None
    assert result["first"]["errors"] == [{"phase": "renderer_destroy", "errorName": "Error"}]


@pytest.mark.parametrize("page", ["pretrip", "debug"])
def test_replacement_cancels_old_pending_renderer_without_triggering_fallback(page: str) -> None:
    result = _canonical(page, """
const previous = activate(); const replacement = activate(); requests[1].resolve();
await Promise.all([previous, replacement]);
const activeIsReplacement = current.mapLibreRenderer === requests[1].renderer;
const receipt = await dispose();
console.log(JSON.stringify({activeIsReplacement, receipt, created, removed, fallback}));
""")
    assert result["activeIsReplacement"] is True
    assert result["receipt"]["disposed"] is True
    assert result["created"] == result["removed"] == 2
    assert result["fallback"] == 0
