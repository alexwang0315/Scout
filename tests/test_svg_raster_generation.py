import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "docs/admin/phase4-pretrip-planning.html"


def _run(probe: str) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for SVG raster generation tests")
    html = PAGE.read_text(encoding="utf-8")
    names = (
        "rasterLayerTileGenerationKey", "mapViewStateSnapshot", "rememberRudyMapView",
        "discardPendingRasterLayerGeneration", "replaceRasterLayerWhenReady",
    )
    functions = []
    for name in names:
        match = re.search(rf"(?ms)^    function {name}\(.*?^    \}}", html)
        assert match, name
        functions.append(match.group(0))
    program = r"""
const {JSDOM} = require("jsdom");
const {window} = new JSDOM('<!doctype html><svg id="map" xmlns="http://www.w3.org/2000/svg"></svg>');
const document = window.document;
const svg = document.getElementById("map");
const RASTER_TILE_SWAP_TIMEOUT_MS = 12000;
const state = {zoom: 113.29, panX: 134, panY: 40, mapRenderer: {active: "svg"}};
const failures = [], statusUpdates = [];
const updateRudyTileStatus = group => statusUpdates.push(group.dataset.activeTileGenerationKey);
const enforceMapRenderPolicy = () => {};
const el = (name, attributes = {}) => {
  const element = document.createElementNS("http://www.w3.org/2000/svg", name);
  Object.entries(attributes).forEach(([key, value]) => element.setAttribute(key, value));
  return element;
};
let now = 0, nextTimer = 1;
const timers = new Map();
window.setTimeout = (callback, delay) => {
  const id = nextTimer++;
  timers.set(id, {callback, due: now + delay});
  return id;
};
window.clearTimeout = id => timers.delete(id);
const advance = milliseconds => {
  const until = now + milliseconds;
  while (true) {
    const due = [...timers.entries()].filter(([, timer]) => timer.due <= until)
      .sort((left, right) => left[1].due - right[1].due || left[0] - right[0])[0];
    if (!due) break;
    now = due[1].due;
    timers.delete(due[0]);
    due[1].callback();
  }
  now = until;
};
const load = image => image.dispatchEvent(new window.Event("load"));
const fail = image => image.dispatchEvent(new window.Event("error"));
""" + "\n".join(functions) + r"""
const group = el("g", {"data-layer-group": "rudy-twmap"});
svg.appendChild(group);
const previousImage = el("image", {href: "/tiles/previous.png", "data-raster-tile": "19/100/200"});
group.appendChild(previousImage);
group.dataset.activeTileGenerationKey = rasterLayerTileGenerationKey(group);
group.dataset.tileGenerationState = "ready";
const start = (name, count, synchronous = false) => {
  const images = [];
  const changed = replaceRasterLayerWhenReady(group, candidate => {
    for (let index = 0; index < count; index += 1) {
      const image = el("image", {href: `/tiles/${name}/${index}.png`,
        "data-raster-tile": `20/${100 + index}/200`});
      candidate.appendChild(image);
      if (synchronous) {
        const setAttribute = image.setAttribute.bind(image);
        image.setAttribute = (key, value) => {
          setAttribute(key, value);
          if (key === "href" && image.parentNode?.parentNode === group) load(image);
        };
      }
      images.push(image);
    }
  }, ({reason, generationKey}) => failures.push({reason, generationKey, at: now}));
  return {images, changed, key: group.dataset.pendingTileGenerationKey};
};
const snapshot = () => ({
  now, state: group.dataset.tileGenerationState,
  previousVisible: group.contains(previousImage), pendingKey: group.dataset.pendingTileGenerationKey || null,
  activeKey: group.dataset.activeTileGenerationKey, timers: timers.size,
  activeImageCount: group.querySelectorAll('[data-tile-generation="active"] image').length,
  failures: [...failures], statusUpdates: [...statusUpdates],
});
""" + "\n" + probe
    completed = subprocess.run(
        [node], input=program, text=True, capture_output=True, cwd=ROOT, timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def test_seventy_tiles_can_make_progress_beyond_twelve_seconds_and_swap_atomically() -> None:
    result = _run("""
const generation = start("native-z20", 70);
let partial;
for (let index = 0; index < 70; index += 1) {
  advance(1000);
  load(generation.images[index]);
  if (index === 63) partial = snapshot();
}
const complete = snapshot();
advance(60000);
console.log(JSON.stringify({partial, complete, later: snapshot()}));
""")
    assert result["partial"]["now"] == 64000
    assert result["partial"]["state"] == "loading"
    assert result["partial"]["previousVisible"] is True
    assert result["partial"]["activeImageCount"] == 0
    assert result["partial"]["failures"] == []
    complete = result["complete"]
    assert complete["state"] == "ready"
    assert complete["previousVisible"] is False
    assert complete["activeImageCount"] == 70
    assert complete["timers"] == 0
    assert len(complete["statusUpdates"]) == 1
    assert result["later"]["failures"] == []
    assert result["later"]["timers"] == 0


def test_stall_times_out_twelve_seconds_after_the_last_new_tile() -> None:
    result = _run("""
const generation = start("stalled", 3);
advance(9000);
load(generation.images[0]);
advance(11999);
const before = snapshot();
advance(1);
console.log(JSON.stringify({before, after: snapshot(), hrefs: generation.images.map(image => image.getAttribute("href"))}));
""")
    assert result["before"]["state"] == "loading"
    assert result["before"]["previousVisible"] is True
    assert result["after"]["state"] == "retained-previous"
    assert result["after"]["failures"][0]["reason"] == "timeout"
    assert result["after"]["failures"][0]["at"] == 21000
    assert result["after"]["timers"] == 0
    assert result["hrefs"] == [None, None, None]


def test_duplicate_load_event_does_not_extend_the_idle_deadline() -> None:
    result = _run("""
const generation = start("duplicate", 2);
advance(9000);
load(generation.images[0]);
advance(11000);
load(generation.images[0]);
advance(1000);
console.log(JSON.stringify(snapshot()));
""")
    assert result["state"] == "retained-previous"
    assert result["failures"][0]["at"] == 21000
    assert result["timers"] == 0


def test_image_error_cancels_the_timer_and_retains_previous_tiles() -> None:
    result = _run("""
const generation = start("broken", 3);
advance(1000);
load(generation.images[0]);
advance(1000);
fail(generation.images[1]);
const failed = snapshot();
load(generation.images[2]);
advance(60000);
console.log(JSON.stringify({failed, later: snapshot()}));
""")
    assert result["failed"]["state"] == "retained-previous"
    assert result["failed"]["previousVisible"] is True
    assert result["failed"]["timers"] == 0
    assert len(result["later"]["failures"]) == 1
    assert result["later"]["failures"][0]["reason"] == "load-error"
    assert result["later"]["statusUpdates"] == []


def test_superseded_generation_timeout_cannot_clear_the_current_generation() -> None:
    result = _run("""
start("older", 2);
advance(6000);
const current = start("current", 2);
advance(4000);
load(current.images[0]);
advance(2000);
const afterOldTimeout = snapshot();
advance(1000);
load(current.images[1]);
console.log(JSON.stringify({currentKey: current.key, afterOldTimeout, complete: snapshot()}));
""")
    assert result["afterOldTimeout"]["state"] == "loading"
    assert result["afterOldTimeout"]["pendingKey"] == result["currentKey"]
    assert result["afterOldTimeout"]["failures"] == []
    assert result["complete"]["state"] == "ready"
    assert result["complete"]["timers"] == 0


def test_reusing_a_generation_key_does_not_allow_old_load_events_to_promote_it() -> None:
    result = _run("""
const old = start("same-key", 2);
advance(1000);
start("middle", 2);
advance(1000);
const current = start("same-key", 2);
load(old.images[0]);
load(old.images[1]);
const afterOldLoads = snapshot();
load(current.images[0]);
load(current.images[1]);
advance(20000);
console.log(JSON.stringify({currentKey: current.key, afterOldLoads, complete: snapshot()}));
""")
    assert result["afterOldLoads"]["state"] == "loading"
    assert result["afterOldLoads"]["pendingKey"] == result["currentKey"]
    assert result["afterOldLoads"]["previousVisible"] is True
    assert result["afterOldLoads"]["activeImageCount"] == 0
    assert result["complete"]["state"] == "ready"
    assert result["complete"]["failures"] == []
    assert result["complete"]["timers"] == 0
    assert len(result["complete"]["statusUpdates"]) == 1


def test_synchronous_cached_loads_leave_no_timer_after_promotion() -> None:
    result = _run("""
start("synchronous-cache", 3, true);
const complete = snapshot();
advance(60000);
console.log(JSON.stringify({complete, later: snapshot()}));
""")
    assert result["complete"]["state"] == "ready"
    assert result["complete"]["activeImageCount"] == 3
    assert result["complete"]["timers"] == 0
    assert result["later"]["failures"] == []


def test_repeated_render_without_new_tiles_does_not_extend_the_deadline() -> None:
    result = _run("""
start("same-render", 2);
advance(11000);
const repeated = start("same-render", 2);
advance(1000);
console.log(JSON.stringify({changed: repeated.changed, final: snapshot()}));
""")
    assert result["changed"] is False
    assert result["final"]["state"] == "retained-previous"
    assert result["final"]["failures"][0]["at"] == 12000
    assert result["final"]["timers"] == 0
