"""Visible-time initialization deadlines; real bundled inline-style RAF replay.

The vendor methods are executed with a deterministic frame scheduler, not a GPU
or live browser. Real Main/Weather/Debug visibility checks remain a separate gate.
"""

import json
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / "docs/admin/scout-maplibre-evidence.js"
VENDOR = ROOT / "docs/admin/vendor/maplibre-gl/6.2.0/maplibre-gl.mjs"


def _run(probe: str, *, vendor: bool = False) -> dict:
    node = shutil.which("node")
    assert node, "Node is required for the hidden initializer regression gate"
    source = ADAPTER.read_text(encoding="utf-8")
    function = "function waitForMapLoad(" + source.split("function waitForMapLoad(", 1)[1].split(
        "  function rasterTileCoverage", 1
    )[0]
    vendor_methods = ""
    if vendor:
        bundled = VENDOR.read_text(encoding="utf-8")
        frame = bundled.split("const Nr={", 1)[1].split(",getImageData(", 1)[0]
        load = "loadJSON(" + bundled.split("loadJSON(", 1)[1].split("loadEmpty(){", 1)[0]
        assert "requestAnimationFrame" in frame
        assert "Nr.frameAsync(this._frameRequest,this.map._ownerWindow)" in load
        vendor_methods = "const Nr={" + frame + "};\nconst vendorStyle={" + load + "};\n"
    program = r"""
global.window = globalThis;
let now = 1000, nextTimer = 1, nextFrame = 1;
Date.now = () => now;
const timers = new Map(), frames = new Map(), visibilityHooks = new Set();
global.document = {
  visibilityState: "visible",
  addEventListener(type, fn) {if(type === "visibilitychange") visibilityHooks.add(fn);},
  removeEventListener(type, fn) {if(type === "visibilitychange") visibilityHooks.delete(fn);}
};
global.setTimeout = (fn, delay) => {
  const id = nextTimer++; timers.set(id, {fn, delay, due: now + delay}); return id;
};
global.clearTimeout = id => timers.delete(id);
global.requestAnimationFrame = fn => {const id=nextFrame++; frames.set(id,fn);return id;};
global.cancelAnimationFrame = id => frames.delete(id);
const advance = ms => {
  const target = now + ms; let iterations = 0;
  while (true) {
    const row = [...timers.entries()].sort((a,b) => a[1].due-b[1].due)[0];
    if (!row || row[1].due > target) break;
    if (++iterations > 100) throw new Error("timer loop");
    now=row[1].due;timers.delete(row[0]);row[1].fn();
  }
  now=target;
};
const visibility = value => {
  document.visibilityState=value;
  for(const fn of [...visibilityHooks]) fn();
};
const flushFrames = () => {
  if(document.visibilityState !== "visible") return;
  for(const [id,fn] of [...frames]) {frames.delete(id);fn(now);}
};
// The vendor frame helper uses its abort-subscription utility and abort error.
const Ae = (signal, type, fn) => {
  signal.addEventListener(type,fn);return {unsubscribe:()=>signal.removeEventListener(type,fn)};
};
class O extends Error {}
class Hr {constructor(type){this.type=type;}}
const host={dataset:{},getBoundingClientRect:()=>({width:756,height:540})};
class MapFixture {
  constructor(){this.handlers=new Map();this.ready=false;this.styleReady=false;this.sources={};}
  loaded(){return this.ready;}
  isStyleLoaded(){return this.styleReady;}
  areTilesLoaded(){return Object.values(this.sources).every(Boolean);}
  getCanvas(){return {width:1512,height:1080};}
  getStyle(){return {sources:Object.fromEntries(Object.keys(this.sources).map(id=>[id,{}]))};}
  isSourceLoaded(id){return this.sources[id];}
  on(type,fn){if(!this.handlers.has(type))this.handlers.set(type,new Set());this.handlers.get(type).add(fn);}
  off(type,fn){this.handlers.get(type)?.delete(fn);}
  fire(type,data={}){for(const fn of [...(this.handlers.get(type)||[])])fn(data);}
  listenerCount(){return [...this.handlers.values()].reduce((n,s)=>n+s.size,0);}
}
const map=new MapFixture();
const receipt=()=>JSON.parse(host.dataset.maplibreInitReceipt);
const cleanup=()=>({timers:timers.size,visibilityHooks:visibilityHooks.size,mapHooks:map.listenerCount()});
const drain=async()=>{await Promise.resolve();await Promise.resolve();await Promise.resolve();};
"""
    program += "\n" + function + "\n" + vendor_methods
    program += "\n(async()=>{\n" + probe + "\n})().catch(e=>{console.error(e);process.exit(1);});"
    result = subprocess.run([node, "-e", program], text=True, capture_output=True, check=True)
    return json.loads(result.stdout)


def test_real_vendor_inline_style_waits_for_foreground_frame_without_expiring() -> None:
    result = _run(r"""
visibility("hidden");let outcome="pending";
const pending=waitForMapLoad(map,20000,host).then(()=>outcome="loaded",e=>outcome=e.message);
const style=Object.assign({},vendorStyle,{map:{_ownerWindow:window},fire:()=>{},
  _load(value){map.styleReady=true;map.sources={"scout-evidence":true};map.fire("style.load");
    map.fire("render");map.ready=true;map.fire("load");}});
style.loadJSON({version:8,sources:{},layers:[]});
advance(22901);flushFrames();await drain();
const hidden={outcome,receipt:receipt(),frames:frames.size,...cleanup()};
visibility("visible");flushFrames();await pending;
console.log(JSON.stringify({hidden,outcome,final:receipt(),cleanup:cleanup()}));
""", vendor=True)
    assert result["hidden"]["outcome"] == "pending"
    assert result["hidden"]["frames"] == 1
    assert result["hidden"]["timers"] == 0
    assert result["hidden"]["receipt"]["phase"] == "waiting_hidden"
    assert result["hidden"]["receipt"]["sourceCount"] == 0
    assert result["outcome"] == "loaded"
    assert result["final"]["hiddenElapsedMs"] == 22901
    assert result["final"]["visibleElapsedMs"] == 0
    assert result["final"]["styleLoadEventSeen"] is True
    assert result["final"]["firstRenderElapsedMs"] == 22901
    assert result["cleanup"] == {"timers": 0, "visibilityHooks": 0, "mapHooks": 0}


def test_visible_initialization_still_times_out_at_twenty_seconds() -> None:
    result = _run(r"""
let outcome="pending";const pending=waitForMapLoad(map,20000,host).catch(e=>outcome=e.message);
advance(19999);await drain();const before=outcome;advance(1);await pending;
console.log(JSON.stringify({before,outcome,receipt:receipt(),cleanup:cleanup()}));
""")
    assert result["before"] == "pending"
    assert result["outcome"] == "maplibre_initialization_timeout"
    assert result["receipt"]["deadlineBasis"] == "visible-time"
    assert result["receipt"]["visibleElapsedMs"] == 20000
    assert result["receipt"]["hiddenElapsedMs"] == 0
    assert result["cleanup"] == {"timers": 0, "visibilityHooks": 0, "mapHooks": 0}


def test_visible_hidden_visible_preserves_remaining_deadline() -> None:
    result = _run(r"""
let outcome="pending";const pending=waitForMapLoad(map,20000,host).catch(e=>outcome=e.message);
advance(6000);visibility("hidden");advance(60000);await drain();const hidden=outcome;
visibility("visible");const remaining=[...timers.values()][0].delay;
advance(13999);await drain();const before=outcome;advance(1);await pending;
console.log(JSON.stringify({hidden,remaining,before,outcome,receipt:receipt(),cleanup:cleanup()}));
""")
    assert result["hidden"] == result["before"] == "pending"
    assert result["remaining"] == 14000
    assert result["outcome"] == "maplibre_initialization_timeout"
    assert result["receipt"]["visibleElapsedMs"] == 20000
    assert result["receipt"]["hiddenElapsedMs"] == 60000
    assert result["receipt"]["elapsedMs"] == 80000
    assert result["receipt"]["visibilityTransitionCount"] == 2
    assert result["cleanup"] == {"timers": 0, "visibilityHooks": 0, "mapHooks": 0}


def test_hidden_abort_removes_all_hooks_and_late_load_cannot_replace_receipt() -> None:
    result = _run(r"""
visibility("hidden");const controller=new AbortController();
const pending=waitForMapLoad(map,20000,host,controller.signal).catch(e=>({name:e.name,message:e.message}));
advance(30000);controller.abort();const outcome=await pending, cancelled=receipt();
visibility("visible");map.ready=true;map.fire("load");advance(30000);
console.log(JSON.stringify({outcome,cancelled,final:receipt(),cleanup:cleanup()}));
""")
    assert result["outcome"] == {"name": "AbortError", "message": "maplibre_initialization_cancelled"}
    assert result["cancelled"] == result["final"]
    assert result["final"]["phase"] == "cancelled"
    assert result["final"]["hiddenElapsedMs"] == 30000
    assert result["cleanup"] == {"timers": 0, "visibilityHooks": 0, "mapHooks": 0}


def test_hidden_load_can_complete_and_cleanup_without_waiting_for_visibility() -> None:
    result = _run(r"""
visibility("hidden");const pending=waitForMapLoad(map,20000,host);
advance(10000);map.ready=true;map.fire("load");await pending;
console.log(JSON.stringify({receipt:receipt(),cleanup:cleanup()}));
""")
    assert result["receipt"]["phase"] == "loaded"
    assert result["receipt"]["hiddenElapsedMs"] == 10000
    assert result["cleanup"] == {"timers": 0, "visibilityHooks": 0, "mapHooks": 0}


def test_without_visibility_event_capability_original_wall_deadline_is_retained() -> None:
    result = _run(r"""
document.visibilityState="hidden";delete document.removeEventListener;
const pending=waitForMapLoad(map,20000,host).catch(e=>e.message);
const delay=[...timers.values()][0].delay;advance(20000);const outcome=await pending;
console.log(JSON.stringify({delay,outcome,receipt:receipt(),cleanup:cleanup()}));
""")
    assert result["delay"] == 20000
    assert result["outcome"] == "maplibre_initialization_timeout"
    assert result["receipt"]["deadlineBasis"] == "wall-clock"
    assert result["cleanup"] == {"timers": 0, "visibilityHooks": 0, "mapHooks": 0}


def test_error_remains_observation_and_does_not_override_load_success() -> None:
    result = _run(r"""
const pending=waitForMapLoad(map,20000,host);map.fire("error",{error:new Error("fixture")});
advance(4000);map.ready=true;map.fire("load");await pending;
console.log(JSON.stringify({receipt:receipt(),cleanup:cleanup()}));
""")
    assert result["receipt"]["phase"] == "loaded"
    assert [e["type"] for e in result["receipt"]["events"]] == ["start", "error", "load"]
    assert result["cleanup"] == {"timers": 0, "visibilityHooks": 0, "mapHooks": 0}


def test_cancelled_deadline_callback_does_not_corrupt_resumed_or_loaded_state() -> None:
    result = _run(r"""
let outcome="pending";const pending=waitForMapLoad(map,20000,host).then(()=>outcome="loaded",e=>outcome=e.message);
const stale=[...timers.values()][0].fn;
advance(5000);visibility("hidden");advance(30000);visibility("visible");
stale();await drain();const before={outcome,receipt:receipt(),timers:timers.size};
map.ready=true;map.fire("load");await pending;const loaded=receipt();stale();visibility("hidden");
console.log(JSON.stringify({before,outcome,loaded,final:receipt(),cleanup:cleanup()}));
""")
    assert result["before"]["outcome"] == "pending"
    assert result["before"]["timers"] == 1
    assert result["outcome"] == "loaded"
    assert result["loaded"] == result["final"]
    assert result["cleanup"] == {"timers": 0, "visibilityHooks": 0, "mapHooks": 0}


def test_hidden_external_remove_without_abort_finishes_at_original_wall_deadline() -> None:
    result = _run(r"""
visibility("hidden");let outcome="pending";
const pending=waitForMapLoad(map,20000,host).catch(e=>outcome=e.message);
advance(5000);map.fire("remove");
const removed={receipt:receipt(),remaining:[...timers.values()][0].delay,...cleanup()};
advance(14999);await drain();const before=outcome;advance(1);await pending;
console.log(JSON.stringify({removed,before,outcome,final:receipt(),cleanup:cleanup()}));
""")
    assert result["removed"]["remaining"] == 15000
    assert result["removed"]["visibilityHooks"] == result["removed"]["mapHooks"] == 0
    assert result["before"] == "pending"
    assert result["outcome"] == "maplibre_initialization_timeout"
    assert result["final"]["elapsedMs"] == 20000
    assert result["final"]["deadlineBasis"] == "removed-renderer-wall-clock"
    assert result["final"]["visibleElapsedMs"] == 0
    assert result["final"]["hiddenElapsedMs"] == 5000
    assert result["final"]["removedWaitElapsedMs"] == 15000
    assert result["cleanup"] == {"timers": 0, "visibilityHooks": 0, "mapHooks": 0}


def test_hidden_remove_after_wall_deadline_does_not_wait_for_foreground() -> None:
    result = _run(r"""
visibility("hidden");const pending=waitForMapLoad(map,20000,host).catch(e=>e.message);
advance(60000);map.fire("remove");const remaining=[...timers.values()][0].delay;
advance(0);console.log(JSON.stringify({remaining,outcome:await pending,cleanup:cleanup()}));
""")
    assert result["remaining"] == 0
    assert result["outcome"] == "maplibre_initialization_timeout"
    assert result["cleanup"] == {"timers": 0, "visibilityHooks": 0, "mapHooks": 0}


def test_visibility_follows_container_owner_document_not_module_global() -> None:
    result = _run(r"""
const ownerHooks=new Set();const owner={visibilityState:"hidden",
  addEventListener:(type,fn)=>ownerHooks.add(fn),removeEventListener:(type,fn)=>ownerHooks.delete(fn)};
host.ownerDocument=owner;let outcome="pending";
const pending=waitForMapLoad(map,20000,host).then(()=>outcome="loaded",e=>outcome=e.message);
advance(30000);await drain();const hidden={outcome,receipt:receipt(),globalHooks:visibilityHooks.size};
owner.visibilityState="visible";for(const fn of [...ownerHooks])fn();
map.ready=true;map.fire("load");await pending;
console.log(JSON.stringify({hidden,outcome,receipt:receipt(),ownerHooks:ownerHooks.size,cleanup:cleanup()}));
""")
    assert result["hidden"]["outcome"] == "pending"
    assert result["hidden"]["receipt"]["documentVisibility"] == "hidden"
    assert result["hidden"]["globalHooks"] == 0
    assert result["outcome"] == "loaded"
    assert result["receipt"]["hiddenElapsedMs"] == 30000
    assert result["ownerHooks"] == 0
    assert result["cleanup"] == {"timers": 0, "visibilityHooks": 0, "mapHooks": 0}
