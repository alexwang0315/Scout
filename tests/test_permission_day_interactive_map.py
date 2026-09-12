"""Permission daily-map construction evidence; live browser QA remains separate."""

import hashlib
import json
import re
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest


ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "docs/admin/scout-dashboard-v0.1.html"


@pytest.fixture(scope="module", autouse=True)
def _record_source(record_testsuite_property):
    record_testsuite_property("dashboard_source_sha256", hashlib.sha256(PAGE.read_bytes()).hexdigest())


class Elements(HTMLParser):
    def __init__(self, markup: str):
        super().__init__()
        self.rows = []
        self.feed(markup)

    def handle_starttag(self, tag, attrs):
        self.rows.append((tag, dict(attrs)))


def _run(probe: str) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for isolated Permission map checks")
    source = PAGE.read_text(encoding="utf-8")
    names = (
        "permissionCompactAnchorLabel", "permissionMercatorPoint",
        "permissionMercatorLatitude", "permissionDayMapBounds",
        "permissionMapAnchors", "permissionMapAnchor", "permissionDayMapGeometry",
        "permissionDailyLabelAnchors", "permissionDayMapViewportId",
        "renderPermissionDayMap", "bindPermissionDayMaps",
        "navigationRudyBounds", "navigationMercatorY", "navigationMercatorLatitude",
        "navigationRudyTileRange", "navigationRudyTileCount", "navigationRudyBaseZoom",
        "navigationRudyTileUrl", "navigationRudyTileLongitude", "navigationRudyTileLatitude",
        "navigationRudyTileKey", "navigationRudyTileImages", "renderDashboardRudyTileLayer",
        "dashboardMapPointPosition", "navigationTerrainPointPosition",
        "renderDashboardMapControls", "renderDashboardMapViewport", "dashboardMapMaxZoom",
        "dashboardMapScreenSymbolTransform", "createDashboardMapViewportController",
    )
    functions = []
    for name in names:
        match = re.search(rf"(?ms)^    function {name}\(.*?^    \}}", source)
        assert match, name
        functions.append(match.group(0))
    # Include additive pure tile helpers used by the shared renderer, without
    # executing the page, its API clients, or its live data-loading lifecycle.
    listed = set(names)
    for match in re.finditer(r"(?ms)^    function ((?:dashboard|navigation)\w+)\(.*?^    \}", source):
        if match.group(1) not in listed:
            functions.append(match.group(0))
            listed.add(match.group(1))
    constants = []
    for name in (
        "DASHBOARD_RUDY_TILE_SOURCE", "DASHBOARD_RUDY_VIEWBOX",
        "DASHBOARD_RUDY_INITIAL_TILE_LIMIT", "NAVIGATION_RUDY_TILE_SOURCE",
        "NAVIGATION_RUDY_VIEWBOX", "NAVIGATION_RUDY_INITIAL_TILE_LIMIT",
        "DASHBOARD_MAP_RENDER_POLICY", "DASHBOARD_MAP_BOX_ZOOM_MIN_SIZE_PX",
        "DASHBOARD_MAP_BOX_ZOOM_MAX_FACTOR",
    ):
        match = re.search(rf"(?ms)^    const {name} = .*?;", source)
        assert match, name
        constants.append(match.group(0))
    setup = r"""
let selectedProject = 'dongqing_batongguan_historic_trail_newImport';
const projectId = () => selectedProject;
const apiBase = () => '';
const asArray = value => Array.isArray(value) ? value : [];
const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g,
  char => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[char]));
const state = {mapViewportById: {}, permissionBaselineMapContext: {
  project_id: selectedProject,
  route_points: [
    {route_order_m:0, lat:23.46, lon:121.04},
    {route_order_m:500, lat:23.461, lon:121.043},
    {route_order_m:1000, lat:23.464, lon:121.047},
    {route_order_m:1500, lat:23.471, lon:121.055},
    {route_order_m:2000, lat:23.478, lon:121.063},
  ],
  anchors: [
    {anchor_id:'cp.0', route_order_m:0, lat:23.46, lon:121.04, display_label:'Trailhead'},
    {anchor_id:'mcp.1', route_order_m:500, lat:23.461, lon:121.043, display_label:'Camp & creek', source_kind:'mcp', named_context:true},
    {anchor_id:'cp.1', route_order_m:1000, lat:23.464, lon:121.047, display_label:'CP 1'},
    {anchor_id:'cp.2', route_order_m:2000, lat:23.478, lon:121.063, display_label:'Day 2 end'},
  ],
}, permissionBaselineDraft: Object.freeze({candidate_only:true, accepted:false}),
  permissionBaselineReviewChecks: Object.freeze({dayEnds:false}),
};
const day = {mission_day_id:'D1', start_anchor:{anchor_id:'cp.0', route_order_m:0, display_label:'Trailhead'},
  primary_day_end_proposal:{target:{anchor_id:'cp.1', route_order_m:1000, display_label:'CP 1'}}};
const secondDay = {mission_day_id:'D2', start_anchor:{anchor_id:'cp.1', route_order_m:1000},
  primary_day_end_proposal:{target:{anchor_id:'cp.2', route_order_m:2000}}};
let renderedViewports = [];
const document = {querySelectorAll(selector) {
  assert.equal(selector, '[data-permission-day-map] [data-dashboard-map-viewport]');
  return renderedViewports;
}};
const window = {setTimeout: () => 1, clearTimeout() {}};
function viewportIdentity(dayValue) {
  const markup = renderPermissionDayMap(dayValue);
  const identity = /data-permission-map-geometry="([^"]+)"/.exec(markup)[1];
  return {dataset:{dashboardMapViewport:permissionDayMapViewportId(dayValue), permissionMapGeometry:identity}};
}
function mockControllerViewport(dayValue) {
  const viewport = viewportIdentity(dayValue);
  const stage = {style:{}, scrollWidth:760, offsetWidth:760, scrollHeight:248, offsetHeight:248};
  const selection = {hidden:true, style:{}, setAttribute(){}, removeAttribute(){}};
  const live = {textContent:''};
  const controlItems = new Map();
  const controls = {listeners:{}, addEventListener(type, handler) {this.listeners[type] = handler;},
    querySelector(selector) {if (!controlItems.has(selector)) controlItems.set(selector,
      {disabled:false, textContent:'', setAttribute(){}}); return controlItems.get(selector);}};
  const baseZoom = navigationRudyBaseZoom(permissionDayMapGeometry(dayValue).bounds);
  const layer = {dataset:{rudyBaseZoom:String(baseZoom)}};
  viewport.dataset.mapMouseZoom = 'true';
  viewport.dataset.mapWheelZoom = 'false';
  viewport.clientWidth = 760; viewport.clientHeight = 248;
  viewport.listeners = {}; viewport.focus = () => {};
  viewport.getBoundingClientRect = () => ({left:0, top:0, right:760, bottom:248, width:760, height:248});
  viewport.addEventListener = (type, handler) => {viewport.listeners[type] = handler;};
  viewport.querySelector = selector => ({
    '[data-dashboard-map-stage]':stage, '[data-dashboard-map-selection]':selection,
    '[data-dashboard-map-controls]':controls, '[data-dashboard-map-live]':live,
    '[data-dashboard-rudy-tile-layer="true"]':layer,
  })[selector] || null;
  viewport.querySelectorAll = () => [];
  viewport.setPointerCapture = () => {}; viewport.hasPointerCapture = () => false;
  const target = {tagName:'DIV', closest: () => null};
  viewport.key = key => viewport.listeners.keydown({key, target, preventDefault(){}});
  viewport.press = action => controls.listeners.click({target:{closest: () => ({dataset:{mapControl:action}})}});
  viewport.drag = (start, end) => {
    viewport.listeners.pointerdown({button:0, pointerId:1, clientX:start[0], clientY:start[1], target});
    viewport.listeners.pointermove({pointerId:1, clientX:end[0], clientY:end[1], target, preventDefault(){}});
    viewport.listeners.pointerup({pointerId:1, target});
  };
  return viewport;
}
"""
    # The real viewport controller owns every gesture. Raster generation itself
    # has dedicated shared tests; record the calls it receives from this surface.
    controller_seam = r"""
const tileViewRequests = [];
updateDashboardRudyTileLayer = (viewport, view) => tileViewRequests.push({id:viewport.dataset.dashboardMapViewport, ...view});
updateDashboardMapScreenSymbols = () => {};
"""
    program = (
        "const vm = require('node:vm'); const assert = require('node:assert/strict');\n"
        "const context = vm.createContext({assert, URL, URLSearchParams, encodeURIComponent});\n"
        f"const code = {json.dumps(setup + '\n'.join(constants + functions) + controller_seam + '(function(){' + probe + '})()')};\n"
        "process.stdout.write(JSON.stringify(vm.runInContext(code, context, {timeout:5000})));\n"
    )
    completed = subprocess.run(
        [node], input=program, text=True, capture_output=True, cwd=ROOT, timeout=15,
        env={"PATH": str(Path(node).parent), "TZ": "UTC"},
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def test_daily_route_and_cp_share_rudy_projection_in_760_by_248_viewbox():
    result = _run("""
return [day, secondDay].map(value => {
  const geometry = permissionDayMapGeometry(value);
  return {geometry, shared:geometry.anchors.map(anchor => dashboardMapPointPosition(anchor,
    geometry.bounds, geometry.width, geometry.height))};
});
""")
    assert result[0]["geometry"]["bounds"] != result[1]["geometry"]["bounds"]
    for item in result:
        geometry = item["geometry"]
        assert (geometry["width"], geometry["height"]) == (760, 248)
        for anchor, shared in zip(geometry["anchors"], item["shared"], strict=True):
            assert anchor["projected"]["x"] == pytest.approx(shared["x"], abs=1e-5)
            assert anchor["projected"]["y"] == pytest.approx(shared["y"], abs=1e-5)


def test_daily_map_has_native_tile_viewport_controls_and_preserves_candidate_route():
    result = _run("""
const geometry = permissionDayMapGeometry(day), id = permissionDayMapViewportId(day);
return {markup:renderPermissionDayMap(day), id,
  requestedTiles:navigationRudyTileImages(geometry.bounds, geometry.bounds,
    navigationRudyBaseZoom(geometry.bounds), geometry.width, geometry.height, id)};
""")
    markup = result["markup"]
    rows = Elements(markup).rows
    # Initial DOM is deliberately empty/unverified. The shared generation tests
    # exercise binding, progressive loads, atomic promotion, and failures.
    assert not [attrs for tag, attrs in rows if tag == "image"]
    layers = [attrs for _, attrs in rows if "data-dashboard-rudy-tile-layer" in attrs]
    assert len(layers) == 1
    assert layers[0]["data-dashboard-rudy-tile-zoom"] == ""
    assert layers[0]["data-rudy-viewbox-width"] == "760"
    assert layers[0]["data-rudy-viewbox-height"] == "248"
    images = [attrs for tag, attrs in Elements(result["requestedTiles"]).rows if tag == "image"]
    # A short day may fit inside one exact XYZ cell; it must still use the
    # shared native-tile layer, not the former fixed-size composite endpoint.
    assert images
    for attrs in images:
        query = parse_qs(urlparse(attrs["href"]).query)
        assert query["source_id"] == ["happyman_rudy_twmap"]
        assert query["native"] == ["1"]
        assert query["exact"] == ["1"]
        assert "cache_only" not in query
        assert attrs["data-dashboard-map-surface"] == result["id"]
    assert "single-composite" not in markup
    assert "mission-baseline/rudy-background" not in markup
    assert 'viewBox="0 0 760 248"' in markup
    assert 'data-runtime-safety-truth="false"' in markup
    assert 'data-candidate-only="true"' in markup
    controls = {attrs.get("data-map-control") for _, attrs in rows}
    assert {"zoom-in", "zoom-out", "reset", "pan", "box-zoom"} <= controls
    assert any("data-map-rudy-updates" in attrs for _, attrs in rows)
    assert any("data-map-rudy-retry" in attrs for _, attrs in rows)
    anchors = {attrs["data-permission-map-anchor"] for _, attrs in rows if "data-permission-map-anchor" in attrs}
    assert anchors == {"cp.0", "mcp.1", "cp.1"}
    assert "Camp &amp; creek" in markup
    assert 'data-dashboard-map-screen-symbol="true"' in markup


def test_day_and_project_ids_do_not_share_pan_zoom_state():
    result = _run("""
const ids = [day, secondDay, {...day, mission_day_id:'D/1'}, {...day, mission_day_id:'D-1'}]
  .map(permissionDayMapViewportId);
state.permissionBaselineMapContext.project_id = 'another_workspace';
ids.push(permissionDayMapViewportId(day));
return {ids};
""")
    assert len(set(result["ids"])) == 5
    assert all(value.startswith("permission-day-") for value in result["ids"])


def test_rerender_preserves_view_but_changed_day_bounds_reset_only_affected_map():
    result = _run("""
renderedViewports = [viewportIdentity(day), viewportIdentity(secondDay)];
bindPermissionDayMaps();
const firstId = permissionDayMapViewportId(day), secondId = permissionDayMapViewportId(secondDay);
state.mapViewportById[firstId] = {zoom:8, x:-150, y:-70, mode:'pan'};
state.mapViewportById[secondId] = {zoom:4, x:-60, y:-30, mode:'box'};
state.mapViewportById['navigation-workspace-map'] = {zoom:2, x:-20};
bindPermissionDayMaps();
const preserved = {...state.mapViewportById};
const changedDay = {...day, primary_day_end_proposal:secondDay.primary_day_end_proposal};
renderedViewports = [viewportIdentity(changedDay), viewportIdentity(secondDay)];
bindPermissionDayMaps();
return {firstId, secondId, preserved, after:state.mapViewportById,
  baseline:state.permissionBaselineDraft, review:state.permissionBaselineReviewChecks,
  project:selectedProject};
""")
    assert result["preserved"][result["firstId"]]["zoom"] == 8
    assert result["firstId"] not in result["after"]
    assert result["after"][result["secondId"]]["zoom"] == 4
    assert result["after"]["navigation-workspace-map"]["zoom"] == 2
    assert result["baseline"] == {"candidate_only": True, "accepted": False}
    assert result["review"] == {"dayEnds": False}
    assert result["project"] == "dongqing_batongguan_historic_trail_newImport"


def test_daily_controller_operates_buttons_keyboard_drag_fit_and_restores_view():
    result = _run("""
const viewport = mockControllerViewport(day);
renderedViewports = [viewport]; bindPermissionDayMaps();
const controller = createDashboardMapViewportController(viewport);
viewport.press('zoom-in'); const zoomed = controller.getState();
viewport.key('ArrowRight'); const keyed = controller.getState();
viewport.drag([300,120], [340,150]); const dragged = controller.getState();
const next = mockControllerViewport(day);
renderedViewports = [next]; bindPermissionDayMaps();
const restored = createDashboardMapViewportController(next).getState();
viewport.press('reset'); const fitted = controller.getState();
viewport.key('+'); viewport.key('-'); const keyboardFit = controller.getState();
return {zoomed, keyed, dragged, restored, fitted, keyboardFit, tileViewRequests};
""")
    assert result["zoomed"]["zoom"] == 1.25
    assert result["keyed"]["x"] < result["zoomed"]["x"]
    assert result["dragged"]["x"] > result["keyed"]["x"]
    assert result["restored"] == result["dragged"]
    assert result["fitted"] == {"zoom": 1, "x": 0, "y": 0, "mode": "pan"}
    assert result["keyboardFit"] == result["fitted"]
    assert any(item["zoom"] > 1 for item in result["tileViewRequests"])


def test_daily_rectangle_zoom_remains_on_shared_controller():
    result = _run("""
const viewport = mockControllerViewport(day);
const controller = createDashboardMapViewportController(viewport);
viewport.press('box-zoom'); viewport.drag([100,60], [360,190]);
return {view:controller.getState(), gesture:viewport.dataset.mapLastGesture};
""")
    assert 1.25 <= result["view"]["zoom"] <= 4
    assert result["view"]["mode"] == "box"
    assert result["gesture"] == "rectangle-zoom-in"


def test_missing_geometry_exposes_candidate_only_empty_state_without_tiles():
    result = _run("""
state.permissionBaselineMapContext.route_points = [];
return {markup:renderPermissionDayMap(day)};
""")
    assert "Route map unavailable" in result["markup"]
    assert "data-dashboard-map-viewport" not in result["markup"]
    assert 'data-candidate-only="true"' in result["markup"]
    assert 'data-runtime-safety-truth="false"' in result["markup"]


def test_permission_view_identity_binding_precedes_shared_controller_binding():
    source = PAGE.read_text(encoding="utf-8")
    permission = re.search(r"(?ms)^    function bindPermissionControls\(.*?^    \}", source).group(0)
    rendered = re.search(r"(?ms)^    function bindRenderedControls\(.*?^    \}", source).group(0)
    assert "bindPermissionDayMaps();" in permission
    assert rendered.index("bindPermissionControls();") < rendered.index("bindDashboardMapViewports();")
