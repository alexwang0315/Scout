"""Executable shared SVG tile-generation checks; no network or browser verdict."""

import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "docs/admin/scout-dashboard-v0.1.html"


@pytest.fixture(scope="module", autouse=True)
def _record_source(record_testsuite_property):
    record_testsuite_property("dashboard_source_sha256", hashlib.sha256(PAGE.read_bytes()).hexdigest())


def _run(probe: str) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for shared SVG native-tile checks")
    source = PAGE.read_text(encoding="utf-8")
    names = (
        "navigationRudyBounds", "navigationMercatorY", "navigationMercatorLatitude",
        "navigationRudyTileRange", "navigationRudyTileCount", "navigationRudyBaseZoom",
        "navigationRudyTileUrl", "navigationRudyTileLongitude", "navigationRudyTileLatitude",
        "navigationRudyTileKey", "navigationRudyTileImages", "renderDashboardRudyTileLayer",
        "dashboardRudyTilePointPosition", "dashboardRudyNativeBaseZoom",
        "publishDashboardRudyTileState", "dashboardMapSvgVisibleRatios",
        "navigationRudyVisibleBounds", "discardDashboardPendingRudyTileGeneration",
        "stageDashboardRudyTileGeneration", "updateDashboardRudyTileLayer",
        "dashboardMapPointPosition", "dashboardMapMaxZoom",
    )
    functions = []
    for name in names:
        match = re.search(rf"(?ms)^    function {name}\(.*?^    \}}", source)
        assert match, name
        functions.append(match.group(0))
    constants = []
    for name in (
        "DASHBOARD_RUDY_TILE_SOURCE", "DASHBOARD_RUDY_VIEWBOX",
        "DASHBOARD_RUDY_INITIAL_TILE_LIMIT", "DASHBOARD_RUDY_TILE_SWAP_TIMEOUT_MS",
        "NAVIGATION_RUDY_TILE_SOURCE", "NAVIGATION_RUDY_VIEWBOX",
        "NAVIGATION_RUDY_INITIAL_TILE_LIMIT",
    ):
        match = re.search(rf"(?ms)^    const {name} = .*?;", source)
        assert match, name
        constants.append(match.group(0))
    setup = r"""
const assert = require('node:assert/strict');
const {JSDOM} = require('jsdom');
// No resources/runScripts options: the DOM cannot load the tile URLs or page code.
const {window} = new JSDOM('<!doctype html><div id="host"></div>');
const document = window.document;
const CustomEvent = window.CustomEvent;
const projectId = () => 'dongqing_batongguan_historic_trail_newImport';
const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g,
  char => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[char]));
const state = {mapViewportById:{}};
const enforceDashboardMapRenderPolicy = () => {};
const failures = [];
let now = 0, nextTimer = 1;
const timers = new Map();
window.setTimeout = (callback, delay) => {
  const id = nextTimer++; timers.set(id, {callback, due:now + delay}); return id;
};
window.clearTimeout = id => timers.delete(id);
function advance(milliseconds) {
  const until = now + milliseconds;
  while (true) {
    const due = [...timers.entries()].filter(([, timer]) => timer.due <= until)
      .sort((a, b) => a[1].due - b[1].due)[0];
    if (!due) break;
    timers.delete(due[0]); now = due[1].due; due[1].callback();
  }
  now = until;
}
class DOMPoint {
  constructor(x, y) {this.x = x; this.y = y;}
  matrixTransform(m) {return new DOMPoint(m.a*this.x + m.c*this.y + m.e,
    m.b*this.x + m.d*this.y + m.f);}
}
const load = image => image.dispatchEvent(new window.Event('load'));
const fail = image => image.dispatchEvent(new window.Event('error'));
"""
    harness = r"""
const width = 760, height = 248;
const xSpan = .04 / 360;
const yCenter = navigationMercatorY(23.46);
const bounds = {west:121.03, east:121.07,
  north:navigationMercatorLatitude(yCenter - xSpan * height / width / 2),
  south:navigationMercatorLatitude(yCenter + xSpan * height / width / 2)};
const initialMarkup = renderDashboardRudyTileLayer(bounds, 13,
  {surfaceId:'permission-day-dongqing-D1', width, height});
document.getElementById('host').innerHTML = `<div data-dashboard-map-viewport="permission-day-dongqing-D1"
  data-map-rudy-updates="true" data-map-zoom="1"><div data-dashboard-map-stage>
  <svg viewBox="0 0 760 248">${initialMarkup}</svg></div>
  <output data-dashboard-rudy-status></output><output data-map-zoom-level></output></div>`;
const viewport = document.querySelector('[data-dashboard-map-viewport]');
const stage = viewport.querySelector('[data-dashboard-map-stage]');
const svg = stage.querySelector('svg');
const layer = svg.querySelector('[data-dashboard-rudy-tile-layer]');
let cssWidth = 760, cssHeight = 248;
let camera = {zoom:1, x:0, y:0};
function metric(element, name, getter) {Object.defineProperty(element, name, {configurable:true, get:getter});}
metric(viewport, 'clientWidth', () => cssWidth); metric(viewport, 'clientHeight', () => cssHeight);
for (const name of ['offsetWidth', 'scrollWidth']) metric(stage, name, () => cssWidth);
for (const name of ['offsetHeight', 'scrollHeight']) metric(stage, name, () => cssHeight);
viewport.getBoundingClientRect = () => ({left:0, top:0, width:cssWidth, height:cssHeight,
  right:cssWidth, bottom:cssHeight});
metric(svg, 'viewBox', () => ({baseVal:{x:0, y:0, width, height}}));
svg.getScreenCTM = () => {
  const cssScale = Math.min(cssWidth/width, cssHeight/height);
  const scale = cssScale * camera.zoom;
  const e = camera.x + (cssWidth - width*cssScale)/2 * camera.zoom;
  const f = camera.y + (cssHeight - height*cssScale)/2 * camera.zoom;
  return {a:scale, b:0, c:0, d:scale, e, f,
    inverse:() => ({a:1/scale, b:0, c:0, d:1/scale, e:-e/scale, f:-f/scale})};
};
viewport.addEventListener('dashboard-rudy-tile-generation-failed', event => failures.push(event.detail));
function setCamera(zoom, x = (1-zoom)*cssWidth/2, y = (1-zoom)*cssHeight/2) {
  camera = {zoom, x, y}; viewport.dataset.mapZoom = String(zoom);
  stage.style.transform = `translate3d(${x}px, ${y}px, 0) scale(${zoom})`;
  state.mapViewportById[viewport.dataset.dashboardMapViewport] = {...camera};
}
function start(key, zoom, count = 3) {
  const markup = Array.from({length:count}, (_, index) =>
    `<image href="${escapeHtml(navigationRudyTileUrl(zoom, 100+index, 200))}"
      data-dashboard-rudy-tile="${zoom}/${100+index}/200"></image>`).join('');
  stageDashboardRudyTileGeneration(viewport, layer, markup, key, zoom, camera);
  const group = layer.querySelector('[data-dashboard-rudy-tile-generation="pending"]');
  return {group, images:[...group.querySelectorAll('image')]};
}
function snapshot() {
  return {data:{...viewport.dataset}, layer:{...layer.dataset}, camera:{...camera},
    transform:stage.style.transform, status:viewport.querySelector('[data-dashboard-rudy-status]').textContent,
    active:layer.querySelectorAll('[data-dashboard-rudy-tile-generation="active"] image').length,
    pending:layer.querySelectorAll('[data-dashboard-rudy-tile-generation="pending"] image').length,
    timers:timers.size, failures:[...failures]};
}
function requestAt(zoom, x, y) {
  setCamera(zoom, x, y); updateDashboardRudyTileLayer(viewport, camera);
  const images = [...layer.querySelectorAll('[data-dashboard-rudy-tile-generation="pending"] image')];
  return {snapshot:snapshot(), urls:images.map(image => image.getAttribute('href'))};
}
"""
    program = setup + "\n".join(constants + functions) + harness + "\n" + (
        "const result = (function(){" + probe + "})(); process.stdout.write(JSON.stringify(result));"
    )
    env = {"PATH": str(Path(node).parent), "TZ": "UTC"}
    if os.environ.get("NODE_PATH"):
        env["NODE_PATH"] = os.environ["NODE_PATH"]
    completed = subprocess.run(
        [node], input=program, text=True, capture_output=True, cwd=ROOT, timeout=20, env=env,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def test_initial_group_is_unverified_until_native_images_finish():
    result = _run("""
const initial = snapshot();
const request = requestAt(1);
return {initialMarkup, initial, request};
""")
    assert result["initial"]["active"] == 0
    assert result["initial"]["layer"]["dashboardRudyTileZoom"] == ""
    assert "<image" not in result["initialMarkup"]
    current = result["request"]["snapshot"]["data"]
    assert current["dashboardTileLoadState"] == "loading"
    assert current["dashboardTileVerifiedZoom"] == ""
    assert int(current["dashboardTileRequiredCount"]) > 1
    assert current["dashboardTileSuccessCount"] == "0"
    assert current["dashboardTilePendingCount"] == current["dashboardTileRequiredCount"]


def test_only_all_loaded_images_promote_the_generation_atomically():
    result = _run("""
const generation = start('complete', 16);
load(generation.images[0]); load(generation.images[1]); const partial = snapshot();
load(generation.images[2]); const complete = snapshot();
load(generation.images[2]); advance(60000);
return {partial, complete, later:snapshot()};
""")
    partial = result["partial"]
    assert partial["active"] == 0
    assert partial["data"]["dashboardTileLoadState"] == "loading"
    assert partial["data"]["dashboardTileSuccessCount"] == "2"
    assert partial["data"]["dashboardTilePendingCount"] == "1"
    complete = result["complete"]
    assert complete["active"] == 3
    assert complete["pending"] == 0
    assert complete["data"]["dashboardTileLoadState"] == "ready"
    assert complete["data"]["dashboardTileVerifiedZoom"] == "16"
    assert complete["data"]["dashboardTileZoom"] == "16"
    assert complete["data"]["dashboardTileSuccessCount"] == "3"
    assert complete["data"]["dashboardTileErrorCount"] == "0"
    assert complete["timers"] == 0
    assert result["later"] == complete


def test_one_error_retains_previous_complete_tiles_and_current_camera():
    result = _run("""
const old = start('old-complete', 15, 2); old.images.forEach(load);
setCamera(4, -810, -220); const before = snapshot();
const candidate = start('new-incomplete', 17, 3);
load(candidate.images[0]); fail(candidate.images[1]); const failed = snapshot();
load(candidate.images[2]); advance(60000);
return {before, failed, later:snapshot(), oldRetained:layer.contains(old.group),
  cancelledHrefs:candidate.images.map(image => image.getAttribute('href'))};
""")
    failed = result["failed"]
    assert result["oldRetained"] is True
    assert failed["active"] == 2
    assert failed["pending"] == 0
    assert failed["data"]["dashboardTileLoadState"] == "retained-previous"
    assert failed["data"]["dashboardTileRequestedZoom"] == "17"
    assert failed["data"]["dashboardTileZoom"] == "15"
    assert failed["data"]["dashboardTileVerifiedZoom"] == ""
    assert failed["data"]["dashboardTileSuccessCount"] == "1"
    assert failed["data"]["dashboardTileErrorCount"] == "1"
    assert failed["data"]["dashboardTileUnverifiedCount"] == "1"
    assert failed["camera"] == result["before"]["camera"]
    assert failed["transform"] == result["before"]["transform"]
    assert result["later"] == failed
    assert result["cancelledHrefs"] == [None, None, None]


def test_cancelled_generation_events_and_timeout_cannot_overwrite_new_result():
    result = _run("""
const old = start('superseded', 15); advance(DASHBOARD_RUDY_TILE_SWAP_TIMEOUT_MS / 2);
const current = start('current', 16, 2);
old.images.forEach(load); fail(old.images[0]);
advance(DASHBOARD_RUDY_TILE_SWAP_TIMEOUT_MS / 2 + 1); const afterOldDeadline = snapshot();
current.images.forEach(load); const complete = snapshot();
old.images.forEach(fail); advance(60000);
return {afterOldDeadline, complete, later:snapshot(), oldRemoved:!layer.contains(old.group)};
""")
    before = result["afterOldDeadline"]
    assert before["data"]["dashboardTileLoadState"] == "loading"
    assert before["data"]["dashboardTileRequestedZoom"] == "16"
    assert before["data"]["dashboardTileSuccessCount"] == "0"
    assert before["failures"] == []
    assert result["oldRemoved"] is True
    assert result["complete"]["data"]["dashboardTileVerifiedZoom"] == "16"
    assert result["later"] == result["complete"]


def test_progressing_generation_can_finish_after_the_inactivity_interval():
    result = _run("""
const candidate = start('slow-progress', 18, 4);
for (const image of candidate.images) {
  advance(DASHBOARD_RUDY_TILE_SWAP_TIMEOUT_MS * .6);
  load(image);
}
return {now, interval:DASHBOARD_RUDY_TILE_SWAP_TIMEOUT_MS, complete:snapshot()};
""")
    assert result["now"] > result["interval"] * 2
    assert result["complete"]["data"]["dashboardTileLoadState"] == "ready"
    assert result["complete"]["data"]["dashboardTileSuccessCount"] == "4"
    assert result["complete"]["timers"] == 0
    assert result["complete"]["failures"] == []


@pytest.mark.parametrize("cache_only", [False, True])
def test_native_and_cache_only_requests_both_require_exact_zoom(cache_only):
    result = _run("""
viewport.dataset.mapRudyUpdates = CACHE_ONLY ? 'false' : 'true';
viewport.dataset.mapRudyRetry = '4';
const request = requestAt(1);
return {queries:request.urls.map(url => Object.fromEntries(new URL(url, 'http://local').searchParams))};
""".replace("CACHE_ONLY", json.dumps(cache_only)))
    assert result["queries"]
    for query in result["queries"]:
        assert query["source_id"] == "happyman_rudy_twmap"
        assert query["exact"] == "1"
        assert query["retry"] == "4"
        assert query["cache_only" if cache_only else "native"] == "1"
        assert ("native" if cache_only else "cache_only") not in query


def test_tile_edges_remain_unclamped_and_align_with_route_projection():
    result = _run("""
const z = 16, tx = 54804, ty = 28372;
const lon = x => navigationRudyTileLongitude(x, z);
const lat = y => navigationRudyTileLatitude(y, z);
const clipped = {west:lon(tx+.2), east:lon(tx+.8), north:lat(ty+.15), south:lat(ty+.75)};
const group = document.createElementNS('http://www.w3.org/2000/svg', 'g');
group.innerHTML = navigationRudyTileImages(clipped, clipped, z, width, height, 'permission-day-test');
const image = group.querySelector('image');
const rectangle = Object.fromEntries(['x','y','width','height'].map(key => [key, Number(image.getAttribute(key))]));
const routePoint = dashboardMapPointPosition({lon:lon(tx+.5), lat:lat(ty+.45)}, clipped, width, height);
const tilePoint = {x:rectangle.x + .5*rectangle.width, y:rectangle.y + .45*rectangle.height};
return {rectangle, routePoint, tilePoint};
""")
    rectangle = result["rectangle"]
    assert rectangle["x"] < 0 and rectangle["y"] < 0
    assert rectangle["x"] + rectangle["width"] > 760
    assert rectangle["y"] + rectangle["height"] > 248
    assert result["tilePoint"]["x"] == pytest.approx(result["routePoint"]["x"], abs=0.002)
    assert result["tilePoint"]["y"] == pytest.approx(result["routePoint"]["y"], abs=0.002)


def test_fit_first_plus_and_maximum_request_native_zoom_through_z20():
    result = _run("""
const fit = requestAt(1);
const firstPlus = requestAt(1.25);
const maximum = requestAt(dashboardMapMaxZoom(viewport));
return {fit:fit.snapshot.data, plus:firstPlus.snapshot.data, maximum:maximum.snapshot.data,
  maxUrls:maximum.urls, maxCamera:camera};
""")
    assert int(result["plus"]["dashboardTileRequestedZoom"]) == int(result["fit"]["dashboardTileRequestedZoom"]) + 1
    assert result["maximum"]["dashboardTileRequestedZoom"] == "20"
    assert result["maxUrls"]
    assert all("/20/" in url for url in result["maxUrls"])
    assert result["maximum"]["dashboardTileVerifiedZoom"] == ""


def test_css_letterboxing_and_existing_camera_scale_do_not_inflate_native_base_zoom():
    result = _run("""
cssWidth = 380; cssHeight = 124; setCamera(1);
const small = dashboardRudyNativeBaseZoom(viewport, layer, 1);
cssWidth = 760; const widerOnly = dashboardRudyNativeBaseZoom(viewport, layer, 1);
cssHeight = 248; const doubled = dashboardRudyNativeBaseZoom(viewport, layer, 1);
setCamera(8); const alreadyZoomed = dashboardRudyNativeBaseZoom(viewport, layer, 8);
return {small, widerOnly, doubled, alreadyZoomed};
""")
    assert result["widerOnly"] == result["small"]
    assert result["doubled"] == result["small"] + 1
    assert result["alreadyZoomed"] == result["doubled"]


def test_map_viewport_clips_without_becoming_a_programmatic_scroll_container():
    source = PAGE.read_text(encoding="utf-8")
    rule = re.search(r"(?s)\n    \.dashboard-map-viewport\s*\{(.*?)\}", source)
    assert rule, "Shared map viewport CSS is missing"
    declarations = re.sub(r"(?s)/\*.*?\*/", "", rule.group(1))
    properties = dict(re.findall(r"([\w-]+)\s*:\s*([^;]+);", declarations))
    # Real Chrome at 1.25x reported viewport.scrollTop=52.5 while controller y
    # stayed -52.5 after scrollIntoView of the lower toolbar. overflow:hidden
    # permits that second camera via native scrolling; overflow:clip does not.
    # JSDOM has no layout engine, so the actual scroll/CTM proof remains browser QA.
    assert properties.get("overflow", "").strip() == "clip"
