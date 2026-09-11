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
        pytest.skip("Node is required for SVG raster zoom tests")
    html = PAGE.read_text(encoding="utf-8")
    names = (
        "boundsFor", "lonToMercatorXValue", "latToMercatorYValue",
        "mercatorYValueToLat", "fitBoundsToMapAspect", "mercatorFrameForBounds",
        "coordinateFromMapPointForBounds", "visibleBoundsFor", "mapViewportBox",
        "lonToTileX", "latToTileY", "tileRangeForZoom", "tileCountForZoom",
        "rasterMapWorldPixelScale", "chooseRasterZoom", "mapInteractionMaxZoom",
    )
    functions = []
    for name in names:
        match = re.search(rf"(?ms)^    function {name}\(.*?^    \}}", html)
        assert match, name
        functions.append(match.group(0))
    program = "\n".join(functions) + r"""
const MAP_WIDTH = 1000, MAP_HEIGHT = 720, MAP_VISUAL_PADDING = 56;
const MAP_MIN_ZOOM = 0.6, MAP_MAX_ZOOM = 12000;
const RASTER_MAX_TILES = 64, RUDY_TWMAP_MAX_TILES = 160;
const clamp = (value, min, max) => Math.max(min, Math.min(max, value));
let rect = {width: 756, height: 540};
const svg = {getBoundingClientRect: () => rect};
let range = {min: 5, max: 20};
const rasterZoomRangeFor = () => range;
let rudyEnabled = true;
const layerInputChecked = () => rudyEnabled;
// A route whose actual projected Z14 tile width was 52.78 SVG units.
function routeWithWorldScale(scale) {
  const xSpan = (MAP_WIDTH - 2 * MAP_VISUAL_PADDING) / scale;
  const ySpan = (MAP_HEIGHT - 2 * MAP_VISUAL_PADDING) / scale;
  return {route: {bounds: {
    west: (0.835 - xSpan / 2) * 360 - 180,
    east: (0.835 + xSpan / 2) * 360 - 180,
    south: mercatorYValueToLat(0.433 + ySpan / 2),
    north: mercatorYValueToLat(0.433 - ySpan / 2),
  }}};
}
const state = {view: routeWithWorldScale(864747.52), zoom: 113.29, panX: 0, panY: 0};
const requested = () => chooseRasterZoom(state.view, visibleBoundsFor(state.view), 64, "rudy-twmap");
""" + "\n" + probe
    completed = subprocess.run(
        [node], input=program, text=True, capture_output=True, cwd=ROOT, timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def test_reported_chrome_weather_view_requests_z19_instead_of_z20() -> None:
    result = _run("""
console.log(JSON.stringify({zoom: requested(), pixels: rasterMapWorldPixelScale(state.view, state.zoom)}));
""")
    assert result["zoom"] == 19
    # At Z19 a 256 px tile is displayed at about 140 CSS px in this view.
    assert 130 < result["pixels"] / (2**19) < 150


def test_doubling_map_magnification_advances_one_native_level() -> None:
    result = _run("""
state.zoom = 32;
const before = requested();
state.zoom = 64;
console.log(JSON.stringify({before, after: requested()}));
""")
    assert result == {"before": 17, "after": 18}


def test_fit_then_first_zoom_advances_native_detail() -> None:
    result = _run("""
state.zoom = 1;
const levels = [requested()];
for (let step = 0; step < 3; step += 1) {
  state.zoom *= 1.25;
  levels.push(requested());
}
console.log(JSON.stringify({levels}));
""")
    # Preserve the Fit + first-click contract. Rounding the route-dependent fit
    # level and magnification separately allows at most one extra native level
    # over the level required by current CSS pixels; the tile budget still applies.
    assert result["levels"] == [12, 13, 13, 13]


def test_route_twice_as_wide_requires_one_lower_native_level() -> None:
    result = _run("""
state.zoom = 32;
const before = requested();
state.view = routeWithWorldScale(864747.52 / 2);
console.log(JSON.stringify({before, after: requested()}));
""")
    assert result == {"before": 17, "after": 16}


def test_first_click_detail_policy_adds_at_most_one_native_level() -> None:
    result = _run("""
const levels = [1, 1.25, 1.5625, 2, 2.01, 3.3, 8.2, 32, 113.29].map(zoom => {
  state.zoom = zoom;
  const pixelLevel = Math.ceil(Math.log2(rasterMapWorldPixelScale(state.view, zoom) / 256));
  return {requested: requested(), pixelLevel};
});
console.log(JSON.stringify({levels}));
""")
    differences = {row["requested"] - row["pixelLevel"] for row in result["levels"]}
    assert differences == {0, 1}


def test_viewport_scale_respects_svg_letterboxing() -> None:
    result = _run("""
state.zoom = 32;
const before = requested();
rect = {width: 1512, height: 540};
const widerOnly = requested();
rect = {width: 1512, height: 1080};
console.log(JSON.stringify({before, widerOnly, doubled: requested()}));
""")
    assert result == {"before": 17, "widerOnly": 17, "doubled": 18}


def test_clipped_route_edge_does_not_inflate_resolution() -> None:
    result = _run("""
const before = requested();
const centeredBounds = visibleBoundsFor(state.view);
state.panX = 440;
const edgeBounds = visibleBoundsFor(state.view);
console.log(JSON.stringify({before, after: requested(),
  centeredWidth: centeredBounds.east - centeredBounds.west,
  edgeWidth: edgeBounds.east - edgeBounds.west}));
""")
    assert result["edgeWidth"] < result["centeredWidth"]
    assert result["before"] == result["after"] == 19


def test_interaction_limit_uses_the_same_native_pixel_scale() -> None:
    result = _run("""
const maximum = mapInteractionMaxZoom();
state.zoom = maximum;
const atMaximum = requested();
const pixelsPerTile = rasterMapWorldPixelScale(state.view, state.zoom) / (2 ** range.max);
range = {min: 5, max: 17};
const lowerMaximum = mapInteractionMaxZoom();
state.zoom = lowerMaximum;
console.log(JSON.stringify({maximum, atMaximum, pixelsPerTile, lowerMaximum, lowerZoom: requested()}));
""")
    assert 413 < result["maximum"] < 415
    assert result["atMaximum"] == 20
    assert result["pixelsPerTile"] == pytest.approx(256)
    assert result["lowerMaximum"] == pytest.approx(result["maximum"] / 8)
    assert result["lowerZoom"] == 17


def test_tile_budget_and_other_raster_selection_remain_effective() -> None:
    result = _run("""
const coverage = {west: -20, east: 20, south: -20, north: 20};
const bounded = chooseRasterZoom(state.view, coverage, 64, "rudy-twmap");
const imagery = chooseRasterZoom(state.view, visibleBoundsFor(state.view), 1024, "imagery");
console.log(JSON.stringify({bounded, count: tileCountForZoom(coverage, bounded),
  nextCount: tileCountForZoom(coverage, bounded + 1), imagery}));
""")
    assert result["count"] <= 160 < result["nextCount"]
    assert result["imagery"] == 20


def test_startup_and_non_rudy_limits_keep_existing_fallback() -> None:
    result = _run("""
rudyEnabled = false;
const otherLayer = mapInteractionMaxZoom();
rudyEnabled = true;
state.view = null;
console.log(JSON.stringify({otherLayer, beforeLoad: mapInteractionMaxZoom(),
  unavailableScale: rasterMapWorldPixelScale(state.view)}));
""")
    assert result == {"otherLayer": 12000, "beforeLoad": 12000, "unavailableScale": None}
