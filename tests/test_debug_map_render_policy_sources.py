"""Diagnostic source inventory reads the active style without GeoJSON payloads."""

import json
import shutil
import subprocess
from pathlib import Path


PAGE = Path(__file__).resolve().parents[1] / "docs/admin/phase-3-5-runtime-debug.html"
ADAPTER = PAGE.parent / "scout-maplibre-evidence.js"


def _inventory(state: dict) -> dict:
    text = PAGE.read_text()
    body = text.split("      getRenderPolicySources() {", 1)[1].split("\n      inspectLayerOrder()", 1)[0]
    method = "function getRenderPolicySources() {" + body.rstrip().removesuffix(",")
    program = "const input = " + json.dumps(state) + ";\n" + """
global.window = globalThis;
require(process.argv[1]);
const debugPageState = {mapRenderer: {active: input.active}, mapLibreRenderer:
  input.style ? {map: {getStyle: () => input.style}, rasterTransport: {
    layers: new Map(Object.entries(input.transport || {})),
    sourceDefinition: layer => ({tiles: layer.protocolTiles}),
  }} : null};
""" + method + "\nconsole.log(JSON.stringify(getRenderPolicySources()));"
    node = shutil.which("node")
    assert node, "Node is required to execute the actual Debug source inventory"
    result = subprocess.run([node, "-e", program, str(ADAPTER)], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def test_inventory_reads_actual_raster_and_image_sources_without_raw_evidence() -> None:
    result = _inventory({"active": "maplibre", "style": {"sources": {
        "rudy": {"type": "raster", "tiles": ["scout-raster-1://rudy/{z}/{x}/{y}"], "tileSize": 256, "maxzoom": 20},
        "terrain": {"type": "image", "url": "/terrain.png", "coordinates": [[120, 24], [121, 24], [121, 23], [120, 23]]},
        "private-route": {"type": "geojson", "data": {"properties": {"unrelated": "do not emit"}}},
    }, "layers": [{"id": "rudy-style", "type": "raster", "source": "rudy",
        "metadata": {"scout:layer_id": "rudy-twmap", "unrelated": "do not emit"}},
        {"id": "terrain-style", "type": "raster", "source": "terrain", "metadata": {"scout:source_type": "image"}}]}})
    assert result["available"] is True and result["activeRenderer"] == "maplibre"
    assert [source["id"] for source in result["sources"]] == ["rudy", "terrain"]
    assert result["sources"][0]["tiles"] == ["scout-raster-1://rudy/{z}/{x}/{y}"]
    assert result["sources"][0]["layers"][0]["metadata"] == {"scout:layer_id": "rudy-twmap"}
    assert result["sources"][1]["type"] == "image" and len(result["sources"][1]["coordinates"]) == 4
    assert "do not emit" not in json.dumps(result)


def test_http_templates_require_actual_style_to_transport_mapping() -> None:
    state = {"active": "maplibre", "style": {
        "sources": {"rudy": {"type": "raster", "tiles": ["scout-raster-1://1/rudy-twmap/0/{z}/{x}/{y}"]}},
        "layers": [{"id": "rudy-style", "type": "raster", "source": "rudy", "metadata": {"scout:layer_id": "rudy-twmap"}}],
    }, "transport": {"rudy-twmap": {"layer": {"map_source_id": "rudy", "protocolTiles": ["scout-raster-1://1/rudy-twmap/0/{z}/{x}/{y}"]},
        "templates": ["http://scout.test/tiles/{z}/{x}/{y}?native=1&exact=1"]}}}
    assert _inventory(state)["sources"][0]["requestTemplates"] == ["http://scout.test/tiles/{z}/{x}/{y}?native=1&exact=1"]
    state["style"]["sources"]["rudy"]["tiles"] = ["scout-raster-1://0/rudy-twmap/0/{z}/{x}/{y}"]
    assert _inventory(state)["sources"][0]["requestTemplates"] is None
    state["style"]["sources"]["rudy"]["tiles"] = state["transport"]["rudy-twmap"]["layer"]["protocolTiles"]
    state["transport"]["rudy-twmap"]["layer"]["map_source_id"] = "some-other-source"
    assert _inventory(state)["sources"][0]["requestTemplates"] is None


def test_missing_active_map_does_not_claim_empty_inventory_was_verified() -> None:
    assert _inventory({"active": "svg"}) == {"activeRenderer": "svg", "available": False, "sources": []}
