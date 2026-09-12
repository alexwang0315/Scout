"""Bounded public-source evidence for existing MapLibre initialization outcomes."""

import json
import shutil
import subprocess
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "docs/admin/scout-maplibre-evidence.js"


def _run(probe: str) -> dict:
    node = shutil.which("node")
    assert node, "Node is required for the initialization receipt regression gate"
    source = SCRIPT.read_text(encoding="utf-8")
    function = "function waitForMapLoad(" + source.split("function waitForMapLoad(", 1)[1].split(
        "  function rasterTileCoverage", 1
    )[0]
    program = r"""
global.window = globalThis;
global.document = {visibilityState: "visible"};
let now = 1000, nextTimer = 1;
Date.now = () => now;
const timers = new Map();
global.setTimeout = (callback, delay) => {const id = nextTimer++; timers.set(id, {callback, delay}); return id;};
global.clearTimeout = id => timers.delete(id);
const host = {dataset: {}, getBoundingClientRect: () => ({width: 720, height: 400})};
class MapFixture {
  constructor() {this.handlers = new Map(); this.ready = false; this.styleReady = false;
    this.tilesReady = false; this.sources = {"scout-evidence": false, "scout-raster-terrain": false};}
  loaded() {return this.ready;}
  isStyleLoaded() {return this.styleReady;}
  areTilesLoaded() {return this.tilesReady;}
  getCanvas() {return {width: 1440, height: 800};}
  getStyle() {return {sources: Object.fromEntries(Object.keys(this.sources).map(key => [key, {}]))};}
  isSourceLoaded(id) {return this.sources[id];}
  on(type, callback) {if (!this.handlers.has(type)) this.handlers.set(type, new Set()); this.handlers.get(type).add(callback);}
  off(type, callback) {this.handlers.get(type)?.delete(callback);}
  fire(type, data = {}) {now += 10; for (const callback of [...(this.handlers.get(type) || [])]) callback(data);}
  listenerCount() {return [...this.handlers.values()].reduce((sum, handlers) => sum + handlers.size, 0);}
}
const map = new MapFixture();
const receipt = () => JSON.parse(host.dataset.maplibreInitReceipt);
const expire = () => {const timer = [...timers.values()][0]; now += timer.delay; timer.callback();};
"""
    program += "\n" + function + "\n(async () => {\n" + probe
    program += "\n})().catch(error => {console.error(error); process.exit(1);});"
    result = subprocess.run([node, "-e", program], text=True, capture_output=True, check=True)
    return json.loads(result.stdout)


def test_success_receipt_keeps_public_readiness_and_cleans_all_hooks() -> None:
    result = _run("""
const pending = waitForMapLoad(map, 20000, host);
map.fire("style.load");
map.sources["scout-evidence"] = true;
map.fire("sourcedata", {sourceId: "scout-evidence", sourceDataType: "content", isSourceLoaded: true});
map.sources["scout-raster-terrain"] = true;
map.ready = map.styleReady = map.tilesReady = true;
map.fire("load"); await pending;
console.log(JSON.stringify({receipt: receipt(), hooks: map.listenerCount(), timers: timers.size}));
""")
    assert result["receipt"]["phase"] == "loaded"
    assert result["receipt"]["styleLoadEventSeen"] is True
    assert result["receipt"]["styleReady"] is True
    assert result["receipt"]["allTilesLoaded"] is True
    assert result["receipt"]["documentVisibility"] == "visible"
    assert result["receipt"]["containerWidth"] == 720
    assert result["receipt"]["canvasWidth"] == 1440
    assert result["receipt"]["waitingSourceIds"] == []
    assert result["receipt"]["events"][2]["sourceId"] == "scout-evidence"
    assert result["hooks"] == result["timers"] == 0


def test_timeout_preserves_actual_waiting_sources_and_original_error() -> None:
    result = _run("""
const pending = waitForMapLoad(map, 20000, host).catch(error => error.message);
map.fire("style.load"); map.sources["scout-evidence"] = true;
map.fire("sourcedata", {sourceId: "scout-evidence", sourceDataType: "content", isSourceLoaded: true});
expire(); const error = await pending;
console.log(JSON.stringify({receipt: receipt(), error, hooks: map.listenerCount(), timers: timers.size}));
""")
    assert result["error"] == "maplibre_initialization_timeout"
    assert result["receipt"]["phase"] == "timeout"
    assert result["receipt"]["waitingSourceIds"] == ["scout-raster-terrain"]
    assert result["receipt"]["styleLoadEventSeen"] is True
    assert result["receipt"]["styleReady"] is False
    assert result["receipt"]["elapsedMs"] >= 20000
    assert result["hooks"] == result["timers"] == 0


def test_receipt_is_bounded_and_excludes_error_messages_urls_and_unknown_ids() -> None:
    result = _run("""
const pending = waitForMapLoad(map, 15000, host).catch(error => error.message);
for (let i = 0; i < 100; i++) map.fire("sourcedata", {sourceId: "scout-evidence", sourceDataType: "content", isSourceLoaded: false});
map.fire("error", {sourceId: "https://secret.example/?token=private", url: "https://private.example", error: new Error("Bearer hidden-secret")});
expire(); await pending;
console.log(JSON.stringify({receipt: receipt(), raw: host.dataset.maplibreInitReceipt}));
""")
    assert len(result["receipt"]["events"]) == 64
    assert result["receipt"]["events"][0]["type"] == "start"
    assert result["receipt"]["events"][-1]["type"] == "timeout"
    assert result["receipt"]["droppedEvents"] == 39
    assert result["receipt"]["events"][-2]["errorName"] == "Error"
    for forbidden in ("hidden-secret", "private.example", "secret.example", "Bearer", "token="):
        assert forbidden not in result["raw"]


def test_remove_is_observed_without_changing_existing_timeout_semantics() -> None:
    result = _run("""
const pending = waitForMapLoad(map, 20000, host).catch(error => error.message);
map.fire("remove"); const hooksAfterRemove = map.listenerCount();
expire(); const error = await pending;
console.log(JSON.stringify({receipt: receipt(), error, hooksAfterRemove, timers: timers.size}));
""")
    assert "remove" in [event["type"] for event in result["receipt"]["events"]]
    assert result["error"] == "maplibre_initialization_timeout"
    assert result["hooksAfterRemove"] == result["timers"] == 0


def test_already_loaded_map_has_receipt_without_hooks_or_timer() -> None:
    result = _run("""
map.ready = map.styleReady = map.tilesReady = true;
map.sources = {"scout-evidence": true}; await waitForMapLoad(map, 20000, host);
console.log(JSON.stringify({receipt: receipt(), hooks: map.listenerCount(), timers: timers.size}));
""")
    assert result["receipt"]["phase"] == "already_loaded"
    assert result["receipt"]["events"][-1]["type"] == "already_loaded"
    assert result["hooks"] == result["timers"] == 0


def test_source_snapshot_explicitly_reports_unknown_and_truncation() -> None:
    result = _run("""
map.sources = Object.fromEntries(Array.from({length: 70}, (_, index) => ["source-" + index, index === 0 ? undefined : false]));
const pending = waitForMapLoad(map, 20000, host).catch(error => error.message); expire(); await pending;
console.log(JSON.stringify(receipt()));
""")
    assert result["sourceCount"] == 70
    assert result["sourcesTruncated"] is True
    assert result["unknownSourceIds"] == ["source-0"]
    assert len(result["waitingSourceIds"]) == 63


def test_first_render_and_document_visibility_are_observed_without_event_flood() -> None:
    result = _run("""
document.visibilityState = "hidden";
const pending = waitForMapLoad(map, 20000, host).catch(error => error.message);
document.visibilityState = "visible";
for (let i = 0; i < 100; i++) map.fire("render");
expire(); await pending;
console.log(JSON.stringify(receipt()));
""")
    assert result["events"][0]["documentVisibility"] == "hidden"
    assert result["documentVisibility"] == "visible"
    assert result["firstRenderElapsedMs"] == 10
    assert [event["type"] for event in result["events"]].count("render") == 1
    assert result["eventCount"] == 3
