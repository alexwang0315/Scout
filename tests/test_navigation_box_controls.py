"""Production Navigation Box/Pan bindings against a bounded MapLibre camera.

This verifies DOM pointer/keyboard wiring and requested camera geometry. It does
not certify browser pointer capture, WebGL drawing, or native tile completion.
"""

import hashlib
import json
from pathlib import Path
import re
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "docs/admin/scout-dashboard-v0.1.html"


@pytest.fixture(scope="module", autouse=True)
def _source_receipt(record_testsuite_property):
    record_testsuite_property("dashboard_source_sha256", hashlib.sha256(PAGE.read_bytes()).hexdigest())


def _replay(body, mode="2d", domain="observed"):
    source = PAGE.read_text()
    functions = "\n".join(re.search(rf"(?ms)^    function {name}\(.*?^    }}", source).group() for name in (
        "configureNavigationTerrainBoxInteraction", "configureNavigationTerrainEvidenceControls",
    ))
    setup = r'''
const assert=require('node:assert/strict'),{JSDOM}=require('jsdom');
const {window}=new JSDOM('<body><main id="map"><div id="canvasContainer"><canvas tabindex="0" aria-keyshortcuts="ArrowUp ArrowDown ArrowLeft ArrowRight + - 0"></canvas></div></main><input id="outside"/></body>');
const document=window.document,host=document.getElementById('map'),canvas=host.querySelector('canvas');
window.fetch=()=>{throw Error('No network is permitted in controls replay')};
const initial={zoom:MODE==='3d'?16:12,bearing:31,pitch:MODE==='3d'?58:0,center:[121.05,23.5]};
let camera=structuredClone(initial),maximum=19,panEnabled=false,nativeBoxEnabled=true;
const animations=[],bindings=[],unbound=[],captures=new Set();
window.HTMLElement.prototype.getBoundingClientRect=()=>({left:40,top:60,width:800,height:500,right:840,bottom:560});
window.HTMLElement.prototype.setPointerCapture=id=>captures.add(id);
window.HTMLElement.prototype.releasePointerCapture=id=>captures.delete(id);
window.HTMLElement.prototype.hasPointerCapture=id=>captures.has(id);
const map={getCanvas:()=>canvas,getCanvasContainer:()=>document.getElementById('canvasContainer'),
  getZoom:()=>camera.zoom,getMaxZoom:()=>maximum,getBearing:()=>camera.bearing,getPitch:()=>camera.pitch,
  getCenter:()=>({lng:camera.center[0],lat:camera.center[1]}),
  unproject:([x,y])=>({lng:camera.center[0]+(x-400)*.0001,lat:camera.center[1]-(y-250)*.0001}),
  easeTo(options){animations.push(options);camera={...camera,...options};},
  zoomOut(){camera.zoom=Math.max(0,camera.zoom-1);},
  dragPan:{enable:()=>{panEnabled=true;},disable:()=>{panEnabled=false;}},
  boxZoom:{disable:()=>{nativeBoxEnabled=false;}},
  on:(name,fn)=>bindings.push([name,fn]),off:(name,fn)=>unbound.push([name,fn])};
host.dataset.navigationEvidenceDomain=DOMAIN;
const entry={host,map,mode:MODE};
const syncNavigationTerrainKeyboardEvidence=()=>{},highlightNavigationTerrainKeyboardFeature=()=>{};
const showDashboardMapHint=()=>{},hideDashboardMapHint=()=>{};
function key(target,value,options={}) {
  const event=new window.KeyboardEvent('keydown',{key:value,bubbles:true,cancelable:true,...options});
  target.dispatchEvent(event);return event;
}
function pointer(target,type,x,y,options={}) {
  const event=new window.MouseEvent(type,{clientX:x+40,clientY:y+60,button:0,buttons:type==='pointerup'?0:1,bubbles:true,cancelable:true,...options});
  Object.defineProperty(event,'pointerId',{value:options.pointerId??11});
  Object.defineProperty(event,'isPrimary',{value:options.isPrimary??true});
  target.dispatchEvent(event);return event;
}
''' .replace("MODE", json.dumps(mode)).replace("DOMAIN", json.dumps(domain))
    setup += functions + r'''
configureNavigationTerrainEvidenceControls(entry);
const pan=host.querySelector('[data-navigation-map-control="pan"]'),box=host.querySelector('[data-navigation-map-control="box-zoom"]');
const capture=host.querySelector('[data-navigation-box-capture]'),overlay=host.querySelector('.scout-maplibre-box-selection');
const minus=document.createElement('button');minus.className='maplibregl-ctrl-zoom-out';host.append(minus);
minus.addEventListener('click',()=>map.zoomOut());
const reset=()=>{camera=structuredClone(initial);};
function drag(from,to,options={}) {
  pointer(capture,'pointerdown',...from,options);pointer(capture,'pointermove',...to,options);pointer(capture,'pointerup',...to,options);
}
'''
    script = setup + "\ntry {\n" + body + "\n} finally { entry.evidenceControlsCleanup();window.close(); }"
    result = subprocess.run(["node"], input=script, text=True, capture_output=True, cwd=ROOT, timeout=30)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("mode", ["2d", "3d"])
@pytest.mark.parametrize("domain", ["observed", "terrain", "prior"])
def test_box_button_b_and_all_four_drag_directions_zoom_in_without_rotating(mode, domain):
    _replay(r'''
assert.ok(box&&pan&&capture);assert.equal(nativeBoxEnabled,false);assert.equal(panEnabled,true);
assert.equal(pan.getAttribute('aria-pressed'),'true');assert.equal(box.getAttribute('aria-pressed'),'false');
assert.match(canvas.getAttribute('aria-keyshortcuts'),/B/);assert.match(box.title,/任意方向/);
const corners=[[[200,100],[600,350]],[[600,350],[200,100]],[[600,100],[200,350]],[[200,350],[600,100]]];
const outcomes=[];
for(const [index,[from,to]] of corners.entries()) {
  reset();
  if(index%2)assert.equal(key(canvas,'b').defaultPrevented,true);else box.click();
  assert.equal(host.dataset.mapInteractionMode,'box');assert.equal(panEnabled,false);
  assert.equal(document.activeElement,canvas);assert.equal(capture.style.pointerEvents,'auto');
  drag(from,to);
  assert.ok(camera.zoom>initial.zoom);assert.ok(camera.zoom<=maximum);
  assert.equal(camera.bearing,initial.bearing);assert.equal(camera.pitch,initial.pitch);
  assert.equal(host.dataset.navigationBoxZoomResult,'zoom-in');assert.equal(overlay.hidden,true);
  assert.equal(captures.size,0);assert.equal(box.getAttribute('aria-pressed'),'true','Box must persist after a rectangle');
  outcomes.push({zoom:camera.zoom,center:camera.center});
  const beforeMinus=camera.zoom;minus.click();assert.ok(camera.zoom<beforeMinus);
}
for(const outcome of outcomes)assert.deepEqual(outcome,outcomes[0],'Drag direction changed the selected view');
assert.equal(animations.length,4);assert.equal(key(canvas,'p').defaultPrevented,true);
assert.equal(host.dataset.mapInteractionMode,'pan');assert.equal(panEnabled,true);assert.equal(capture.style.pointerEvents,'none');
''', mode, domain)


@pytest.mark.parametrize("mode", ["2d", "3d"])
def test_escape_pointer_cancel_pan_switch_and_lost_capture_leave_no_camera_effect(mode):
    _replay(r'''
for(const action of ['escape','pointercancel','pan','lostpointercapture']) {
  reset();box.click();pointer(capture,'pointerdown',150,100);pointer(capture,'pointermove',550,300);
  assert.equal(overlay.hidden,false);assert.equal(captures.size,1);
  if(action==='escape')assert.equal(key(canvas,'Escape').defaultPrevented,true);
  else if(action==='pan')pan.click();
  else pointer(capture,action,550,300);
  assert.equal(overlay.hidden,true);assert.equal(captures.size,0);
  pointer(capture,'pointerup',550,300);
  assert.equal(animations.length,0);assert.deepEqual(camera,initial);
}
''', mode)


def test_disabled_wrong_pointer_modifiers_and_thin_rectangles_do_not_change_camera():
    _replay(r'''
drag([150,100],[550,300]);assert.equal(animations.length,0,'Pan mode must not claim a Box gesture');
box.click();
for(const options of [{button:2},{isPrimary:false},{ctrlKey:true},{altKey:true},{metaKey:true}]) {
  drag([150,100],[550,300],options);assert.equal(animations.length,0);assert.equal(captures.size,0);
}
pointer(capture,'pointerdown',150,100,{pointerId:11});
pointer(capture,'pointermove',550,300,{pointerId:12});pointer(capture,'pointerup',550,300,{pointerId:12});
assert.equal(animations.length,0);assert.equal(captures.size,1);key(canvas,'Escape');
drag([150,100],[550,101]);assert.equal(animations.length,0);assert.equal(host.dataset.navigationBoxZoomResult,'ignored-thin-selection');
assert.equal(overlay.hidden,true);assert.equal(captures.size,0);
const input=document.getElementById('outside');input.focus();
assert.equal(key(input,'p').defaultPrevented,false);assert.equal(host.dataset.mapInteractionMode,'box');
assert.equal(key(canvas,'p',{ctrlKey:true}).defaultPrevented,false);assert.equal(host.dataset.mapInteractionMode,'box');
''')


def test_zoom_ceiling_invalid_coordinates_and_disposal_cannot_fake_a_success():
    _replay(r'''
box.click();camera.zoom=maximum;
drag([150,100],[550,300]);assert.equal(animations.length,0);assert.equal(host.dataset.navigationBoxZoomResult,'at-maximum-or-full-view');
reset();const unproject=map.unproject;map.unproject=()=>({lng:NaN,lat:Infinity});
drag([150,100],[550,300]);assert.equal(animations.length,0);assert.equal(host.dataset.navigationBoxZoomResult,'invalid-camera');
map.unproject=unproject;pointer(capture,'pointerdown',150,100);pointer(capture,'pointermove',550,300);
assert.equal(captures.size,1);entry.evidenceControlsCleanup();
assert.equal(captures.size,0);assert.equal(capture.isConnected,false);assert.equal(overlay.isConnected,false);
assert.equal(host.querySelector('[data-navigation-map-control]'),null);assert.equal(unbound.length,2);
assert.equal(canvas.getAttribute('aria-keyshortcuts'),'ArrowUp ArrowDown ArrowLeft ArrowRight + - 0');
pointer(capture,'pointerup',550,300);box.click();key(canvas,'b');assert.equal(animations.length,0);
''')


@pytest.mark.parametrize("domain", ["observed", "terrain", "prior"])
@pytest.mark.parametrize("loading", [False, True])
def test_production_navigation_svg_ready_and_loading_bind_box_b_and_minus(domain, loading):
    script = r'''
const assert=require('node:assert/strict'),fs=require('node:fs'),{JSDOM}=require('jsdom');
const {window}=new JSDOM('<body/>',{url:'http://localhost/admin/dashboard?projectId=controls_fixture&diagnosticMapProbe=1',runScripts:'outside-only'});
window.matchMedia=()=>({matches:false});window.structuredClone=structuredClone;
window.fetch=()=>{throw Error('Controls replay must not fetch')};
window.Element.prototype.getBoundingClientRect=function(){return {left:0,top:0,width:1000,height:392,right:1000,bottom:392}};
const html=fs.readFileSync('docs/admin/scout-dashboard-v0.1.html','utf8');
const source=[...html.matchAll(/<script(?: [^>]*)?>([\s\S]*?)<\/script>/g)].map(item=>item[1]).find(script=>script.includes('const DIAGNOSTIC_MAP_PROBE'));
window.eval(source+String.raw`
window.replayNavigationSvg=async options=>{
  const before={...state},host=document.createElement('div'),originalUpdate=updateDashboardRudyTileLayer;
  const bounds={west:121.04,east:121.07,south:23.46,north:23.48};
  const snapshot={status:options.loading?'loading':'ready',orientation_basemap:{status:'ready',bounds_wgs84:bounds},
    terrain_surface:{bbox_wgs84:bounds,cell_resolution_m:20},
    route_samples:{points:[{lat:23.463,lon:121.044,distance_m:0},{lat:23.474,lon:121.063,distance_m:1500}]},
    terrain_mesh:{status:'visualization_mesh',minimum_elevation_m:100,maximum_elevation_m:140,
      vertices:[{u:0,v:0,elevation_m:100,supported:true},{u:1,v:0,elevation_m:120,supported:true},{u:0,v:1,elevation_m:140,supported:true}],triangles:[[0,1,2]]}};
  updateDashboardRudyTileLayer=viewport=>{if(viewport.dataset.mapRudyUpdates!=='false')throw Error('Controls enabled network tile updates')};
  document.body.append(host);
  try {
    state.navigationTerrainEvidenceDomain=options.domain;state.navigationTerrainLens='structure';state.mapViewportById={};
    host.innerHTML=options.loading?renderNavigationWorkspaceLoading(snapshot):renderNavigationWorkspaceMap(snapshot,null,null,null,null);
    diagnosticSetMapInteractionCacheOnly(host);
    const viewport=host.querySelector('[data-dashboard-map-viewport]'),stage=viewport.querySelector('[data-dashboard-map-stage]');
    for(const [node,values]of [[viewport,{clientWidth:1000,clientHeight:392}],[stage,{offsetWidth:1000,scrollWidth:1000,offsetHeight:392,scrollHeight:392}]]) {
      for(const [name,value]of Object.entries(values))Object.defineProperty(node,name,{value,configurable:true});
    }
    bindDashboardMapViewports();
    const adapter=diagnosticSharedMapInteractionAdapter(viewport);
    adapter.settle=()=>new Promise(resolve=>window.setTimeout(resolve,0));
    const variant=options.domain+':'+(options.loading?'loading':'fallback')+':structure';
    const surface=diagnosticMapInteractionSurfaceCases().find(item=>item.id==='navigation-map'&&item.renderer==='svg'&&item.variant===variant);
    const rows=await diagnosticExerciseMapInteractionDom(surface,adapter);
    return {rows,workspace:projectId(),candidateOnly:host.textContent.includes('CANDIDATE'),variant};
  } finally {
    host.remove();updateDashboardRudyTileLayer=originalUpdate;
    for(const key of Object.keys(state))if(!(key in before))delete state[key];Object.assign(state,before);
  }
};
`);
(async()=>{
const result=await window.replayNavigationSvg(OPTIONS);
assert.equal(result.workspace,'controls_fixture');
for(const id of ['DASH-027','DASH-029']){const row=result.rows.find(item=>item.check===id);assert.equal(row.status,'passed',id+': '+row.detail)}
const evidence=result.rows.find(item=>item.check==='DASH-027').evidence;
assert.equal(evidence.forwardRectangleZoomIn,true);assert.equal(evidence.reverseRectangleZoomIn,true);assert.equal(evidence.minusZoomOut,true);
assert.equal(evidence.cancelledRectangleCleared,true);assert.equal(evidence.subchecks.find(item=>item.name==='box_keyboard_activation').status,'passed');
})().catch(error=>{console.error(error);process.exitCode=1}).finally(()=>window.close());
'''.replace("OPTIONS", json.dumps({"domain": domain, "loading": loading}))
    result = subprocess.run(["node"], input=script, text=True, capture_output=True, cwd=ROOT, timeout=40)
    assert result.returncode == 0, result.stderr
