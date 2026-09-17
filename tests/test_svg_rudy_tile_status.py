"""SVG cache misses must distinguish displayed detail from requested detail."""
import re
import subprocess
from pathlib import Path

PAGE = Path(__file__).resolve().parents[1] / "docs/admin/phase4-pretrip-planning.html"


def test_svg_cache_miss_preserves_view_and_success_clears_failure():
    source = PAGE.read_text()
    functions = []
    for name in ("retainRudyMapViewAfterTileFailure", "updateRudyTileStatus"):
        match = re.search(rf"(?ms)^    function {name}\(.*?^    }}", source)
        assert match
        functions.append(match.group())
    script = "\n".join(functions) + r'''
const assert = require('node:assert/strict');
let badge = '';
const output = {};
const shell = {dataset:{}};
const document = {getElementById: id => id === 'mapRendererShell' ? shell : output};
const updateMapZoomIndicator = text => {badge = text;};
const chooseRasterZoom = () => 19;
const visibleBoundsFor = () => ({}), boundsFor = () => ({});
const RASTER_MAX_TILES = 120;
const state = {zoom:113.29, panX:133.6, panY:39.59, view:{},
  mapRenderer:{active:'svg'}, rasterRemoteRefreshEnabled:false};
let tiles = ['14/13705/7094'];
const group = {dataset:{layerGroup:'rudy-twmap'},
  querySelectorAll: () => tiles.map(tile => ({getAttribute: () => tile}))};
retainRudyMapViewAfterTileFailure(group);
assert.equal(state.zoom, 113.29);
assert.equal(state.panX, 133.6);
assert.equal(state.panY, 39.59);
assert.equal(group.dataset.requestedTileZoom, '19');
assert.equal(group.dataset.displayedTileZoom, '14');
assert.equal(shell.dataset.mapRasterState, 'degraded');
assert.match(badge, /需要 Z19.*目前 Z14/);
assert.match(output.textContent, /快取未能提供完整 Z19/);
assert.match(output.textContent, /更新圖磚/);
assert.doesNotMatch(output.textContent, /native.*unavailable/);
state.rasterRemoteRefreshEnabled = true;
retainRudyMapViewAfterTileFailure(group, 'timeout');
assert.match(output.textContent, /未能完整載入/);
assert.doesNotMatch(output.textContent, /快取未能/);
tiles = ['19/438591/227030', '19/438592/227030'];
updateRudyTileStatus(group);
assert.equal(group.dataset.displayedTileZoom, '19');
assert.equal(shell.dataset.mapRasterState, 'available');
assert.equal(group.dataset.nativeTileFailure, undefined);
assert.equal(state.lastFailedNativeMapZoom, undefined);
assert.equal(badge, '· 圖磚 Z19');
assert.match(output.textContent, /已載入 Z19/);
assert.match(output.textContent, /停止更新/);
const previousBadge = badge;
state.mapRenderer.active = 'maplibre';
retainRudyMapViewAfterTileFailure(group);
assert.equal(badge, previousBadge, 'Hidden SVG cannot overwrite MapLibre status');
'''
    result = subprocess.run(["node"], input=script, text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
