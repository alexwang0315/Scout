"""Replay the shared Main/Weather SVG control bindings, without loading data.

This runs the production map-only statements inside bindControls. Browser layout,
the outer Weather iframe and tile transport remain separate live checks.
"""

import hashlib
from pathlib import Path
import re
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "docs/admin/phase4-pretrip-planning.html"


@pytest.fixture(scope="module", autouse=True)
def _source_receipt(record_testsuite_property):
    record_testsuite_property("pretrip_source_sha256", hashlib.sha256(PAGE.read_bytes()).hexdigest())


def _replay(body):
    source = PAGE.read_text()
    functions = "\n".join(re.search(rf"(?ms)^    function {name}\(.*?^    }}", source).group() for name in (
        "mapViewBox", "mapViewportBox", "applyMapViewport", "clampMapPan", "panMap", "zoomMap", "resetMapView",
        "zoomActiveMap", "fitActiveMap", "panActiveMap", "setMapInteractionMode", "mapPointFromPointerEvent",
        "boxFromPoints", "updateZoomSelectionOverlay", "clearZoomSelectionOverlay", "zoomMapToBox",
        "selectionZoomFactor", "eventScreenX", "eventScreenY", "beginMapRectangleZoom", "updateMapRectangleZoom",
        "finishMapRectangleZoom", "cancelMapRectangleZoom", "beginMapPointerPan", "updateMapPointerPan",
        "finishMapPointerPan", "cancelMapPointerPan", "handleMapWheelZoom", "mapKeyboardPanDelta",
        "isEditableKeyboardTarget", "handleMapKeyboardPan", "activateMapKeyboardPan", "deactivateMapKeyboardPanOutside",
    ))
    bind = re.search(r"(?ms)^    function bindControls\(.*?^    }", source).group()
    buttons = bind[bind.index('      document.getElementById("zoomIn").addEventListener'):bind.index('      document.getElementById("cpSegmentSearch")')]
    pointers = bind[bind.index('      svg.addEventListener("pointerdown", beginMapRectangleZoom);'):bind.rindex('\n    }')]
    setup = r'''
const assert=require('node:assert/strict'),{JSDOM}=require('jsdom');
const {window}=new JSDOM('<body><svg id="map"></svg><div id="mapLibreEvidenceMap"></div><input id="outside"/></body>');
const document=window.document,svg=document.getElementById('map'),captures=new Set();
for(const id of ['zoomIn','zoomOut','fitRoute','panMode','boxZoomMode','panUp','panDown','panLeft','panRight']) {
  const button=document.createElement('button');button.id=id;document.body.append(button);
}
window.fetch=()=>{throw Error('No network allowed')};
const state={zoom:1,panX:0,panY:0,mapInteractionMode:'pan',mapKeyboardActive:false,mapRenderer:{active:'svg'},selected:null};
const MAP_WIDTH=1000,MAP_HEIGHT=720,MAP_MIN_ZOOM=.6,MAP_ZOOM_STEP_FACTOR=1.25,MAP_WHEEL_ZOOM_ENABLED=false;
const mapInteractionMaxZoom=()=>12000,renderRasterBasemapLayers=()=>{},syncMapMarkerScale=()=>{},updatePointLabels=()=>{};
const updateMapZoomIndicator=()=>{},updateScaleBar=()=>{},highlightMapFor=()=>{};
const setSelectedMapCoordinate=()=>{throw Error('A rectangle must not mutate coordinate selection')};
const coordinateFromMapPointerEvent=()=>{throw Error('A rectangle must not invoke click selection')};
const el=(tag,attrs)=>{const node=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const [key,value]of Object.entries(attrs))node.setAttribute(key,value);return node;};
svg.getBoundingClientRect=()=>({left:40,top:50,width:1000,height:720,right:1040,bottom:770});
svg.getScreenCTM=()=>({inverse:()=>({})});
svg.createSVGPoint=()=>({x:0,y:0,matrixTransform(){const v=mapViewportBox();return {x:v.minX+(this.x-40)*v.width/1000,y:v.minY+(this.y-50)*v.height/720}}});
svg.setPointerCapture=id=>captures.add(id);svg.hasPointerCapture=id=>captures.has(id);svg.releasePointerCapture=id=>captures.delete(id);
const click=id=>document.getElementById(id).click();
function pointer(type,[x,y]){const event=new window.MouseEvent(type,{clientX:x+40,clientY:y+50,button:0,bubbles:true,cancelable:true});Object.defineProperty(event,'pointerId',{value:3});svg.dispatchEvent(event);}
function key(value){const event=new window.KeyboardEvent('keydown',{key:value,bubbles:true,cancelable:true});svg.dispatchEvent(event);return event;}
function drag(from,to){pointer('pointerdown',from);pointer('pointermove',to);pointer('pointerup',to);}
'''
    script = setup + functions + "\n" + buttons + pointers + "\ntry {\n" + body + "\n} finally {window.close();}"
    result = subprocess.run(["node"], input=script, text=True, capture_output=True, cwd=ROOT, timeout=30)
    assert result.returncode == 0, result.stderr


def test_shared_main_weather_bound_controls_zoom_in_in_every_rectangle_direction():
    _replay(r'''
const corners=[[[200,140],[700,500]],[[700,500],[200,140]],[[200,500],[700,140]],[[700,140],[200,500]]];
const outcomes=[];
for(const [index,[from,to]]of corners.entries()) {
  click('fitRoute');svg.focus();
  if(index%2)assert.equal(key('b').defaultPrevented,true);else click('boxZoomMode');
  assert.equal(state.mapInteractionMode,'box');assert.equal(document.getElementById('boxZoomMode').getAttribute('aria-pressed'),'true');
  drag(from,to);assert.ok(state.zoom>1);assert.equal(state.zoomSelection,null);assert.equal(svg.querySelector('#zoomSelection'),null);
  assert.equal(captures.size,0);outcomes.push(svg.getAttribute('viewBox'));
  const before=state.zoom;click('zoomOut');assert.ok(state.zoom<before);
}
assert.ok(outcomes.every(value=>value===outcomes[0]),'Direction changed selected view');
assert.equal(key('p').defaultPrevented,true);assert.equal(state.mapInteractionMode,'pan');
''')


def test_shared_main_weather_escape_and_wheel_do_not_change_camera():
    _replay(r'''
click('fitRoute');svg.focus();key('b');
pointer('pointerdown',[200,140]);pointer('pointermove',[700,500]);
assert.ok(svg.querySelector('#zoomSelection'));assert.equal(key('Escape').defaultPrevented,true);
pointer('pointerup',[700,500]);assert.equal(state.zoom,1);assert.equal(svg.querySelector('#zoomSelection'),null);
assert.equal(state.zoomSelection,null);assert.equal(captures.size,0);
const wheel=new window.WheelEvent('wheel',{deltaY:120,bubbles:true,cancelable:true});svg.dispatchEvent(wheel);
assert.equal(wheel.defaultPrevented,false);assert.equal(state.zoom,1);
''')
