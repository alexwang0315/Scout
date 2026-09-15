"""Production event/focus regressions; DOM replays are not trusted browser or tile proof."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest
from test_pretrip_box_controls import _replay as pretrip_replay
from test_maplibre_initial_view_loading import _run as initial_view_replay
from test_dashboard_map_interaction_factory import _run as factory_replay

ROOT = Path(__file__).resolve().parents[1]
PRETRIP = ROOT / "docs/admin/phase4-pretrip-planning.html"
DASHBOARD = ROOT / "docs/admin/scout-dashboard-v0.1.html"
VENDOR = ROOT / "docs/admin/vendor/maplibre-gl/6.2.0"

@pytest.fixture(scope="module", autouse=True)
def source_receipt(record_testsuite_property):
    for path in (PRETRIP, DASHBOARD, ROOT / "docs/admin/scout-maplibre-evidence.js", VENDOR / "maplibre-gl.mjs"):
        record_testsuite_property(path.name + "_sha256", hashlib.sha256(path.read_bytes()).hexdigest())

def functions(path, *names):
    source = path.read_text()
    return "\n".join(re.search(rf"(?ms)^    (?:async )?function {name}\(.*?^    }}", source).group() for name in names)

def node(script):
    result = subprocess.run(["node"], input=script, capture_output=True, text=True, cwd=ROOT, timeout=35)
    assert result.returncode == 0, result.stderr

def test_shared_main_weather_svg_relinquishes_keys_on_keyboard_focus_exit():
    pretrip_replay(r"""
click('zoomIn');activateMapKeyboardPan();assert.equal(state.mapKeyboardActive,true);
const outsideButton=document.createElement('button');document.body.append(outsideButton);outsideButton.focus();
const before=mapViewBox(),outsideKey=new window.KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true,cancelable:true});
outsideButton.dispatchEvent(outsideKey);
assert.equal(document.activeElement,outsideButton);
assert.equal(outsideKey.defaultPrevented,false,'Keyboard focus exit must stop interception without a mouse click');
assert.equal(mapViewBox(),before);
svg.focus();const beforeInside=mapViewBox();assert.equal(key('ArrowRight').defaultPrevented,true);assert.notEqual(mapViewBox(),beforeInside);
const input=document.getElementById('outside');input.focus();
const editableKey=new window.KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true,cancelable:true});input.dispatchEvent(editableKey);
assert.equal(editableKey.defaultPrevented,false);
""")

def test_embedded_parent_focus_preserves_its_keys_and_child_camera():
    node(r"""
const assert=require('node:assert/strict'),{JSDOM}=require('jsdom');
const dom=new JSDOM('<body><iframe></iframe><button id="parent-outside"></button></body>'),parent=dom.window;
const child=parent.document.querySelector('iframe').contentWindow,document=child.document;
document.body.innerHTML='<svg id="map" tabindex="0"></svg><div id="mapLibreEvidenceMap"><canvas tabindex="0"></canvas></div><button id="child-outside"></button>';
const svg=document.getElementById('map'),state={mapKeyboardActive:true};let pans=0;
const panActiveMap=()=>pans++,zoomActiveMap=()=>{},fitActiveMap=()=>{},setMapInteractionMode=()=>{},cancelMapRectangleZoom=()=>{},cancelMapPointerPan=()=>{};
""" + functions(PRETRIP, "mapKeyboardPanDelta", "isEditableKeyboardTarget", "handleMapKeyboardPan") + r"""
document.addEventListener('keydown',handleMapKeyboardPan);
for(const target of [svg,document.querySelector('canvas')]) {
 target.focus();const inside=new child.KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true,cancelable:true});target.dispatchEvent(inside);
 assert.equal(inside.defaultPrevented,true);
 const count=pans,outside=parent.document.getElementById('parent-outside');outside.focus();
 const key=new parent.KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true,cancelable:true});outside.dispatchEvent(key);
 assert.equal(parent.document.activeElement,outside);assert.equal(key.defaultPrevented,false);assert.equal(pans,count);
 const button=document.getElementById('child-outside');button.focus();
 const childKey=new child.KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true,cancelable:true});button.dispatchEvent(childKey);
 assert.equal(childKey.defaultPrevented,false);assert.equal(pans,count);
}
parent.close();
""")

@pytest.mark.parametrize("tag", ["path", "g"])
def test_svg_highlight_preserves_focused_evidence_and_hint(tag):
    node(r"""
const assert=require('node:assert/strict'),{JSDOM}=require('jsdom');
const dom=new JSDOM('<body><svg id="map"><g id="layer"></g></svg><aside id="hint"></aside></body>'),window=dom.window,document=window.document;
const svg=document.getElementById('map'),layer=document.getElementById('layer'),hint=document.getElementById('hint');
const state={mapRenderer:{active:'svg'},selected:null},item={source_id:'cp-1',evidence_type:'checkpoint'};
const evidenceSourceId=v=>v.source_id,showHint=()=>{hint.hidden=false;},hideHint=()=>{hint.hidden=true;},moveHint=()=>{};
const setDetail=v=>{state.selected=v;},highlightEvidenceTimelineFor=()=>{},highlightTreeNode=()=>{},renderAssistantPromptSuggestions=()=>{},focusMapFor=()=>{};
const target=document.createElementNS('http://www.w3.org/2000/svg',TAG),other=document.createElementNS('http://www.w3.org/2000/svg','path');
layer.append(target,other);const mapTargetsFor=()=>[target];hint.hidden=true;
""".replace("TAG", json.dumps(tag)) + functions(PRETRIP, "attachEvidence", "selectEvidence", "highlightMapFor") + r"""
attachEvidence(target,item);target.focus();
assert.equal(document.activeElement,target,'Moving focused SVG evidence loses focus');
assert.equal(hint.hidden,false);assert.equal(state.selected,item);
const escape=new window.KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true});target.dispatchEvent(escape);
assert.equal(escape.defaultPrevented,true);assert.equal(hint.hidden,true);
target.blur();target.focus();assert.equal(document.activeElement,target);assert.equal(hint.hidden,false);
target.blur();assert.equal(hint.hidden,true);
highlightMapFor(item);assert.equal(layer.lastChild,target,'Unfocused evidence still moves to foreground');window.close();
""")

@pytest.mark.parametrize("enabled", [False, True, None])
def test_maplibre_wheel_policy_applies_before_first_load(enabled):
    extra = "{}" if enabled is None else json.dumps({"scrollZoom": enabled})
    result = initial_view_replay("""
const pending=api.createRenderer(options(EXTRA),collection);
const policy=renderer.map.options.scrollZoom,loading=!renderer.map.loaded();
load();await pending;console.log(JSON.stringify({policy,loading,changes,statuses}));renderer.destroy();
""".replace("EXTRA", extra))
    assert result.get("policy") is (True if enabled is None else enabled)
    assert result["loading"] is True
    assert result["changes"] == []
    assert result["statuses"][-1] == {"state": "ready", "mapLoaded": True}

@pytest.mark.parametrize("enabled", [False, True])
def test_canonical_page_passes_wheel_policy_to_renderer(enabled):
    # Evaluate the actual call argument and callbacks without invoking data loaders.
    node(r"""
const assert=require('node:assert/strict'),fs=require('node:fs');
const html=fs.readFileSync('docs/admin/phase4-pretrip-planning.html','utf8');
const source=html.match(/^    async function activatePretripMapLibreRenderer\([\s\S]*?^    }/m)[0];
const calls=[...source.matchAll(/creation = adapter\.createRenderer\((\{[\s\S]*?^        \}), featureCollection\);/gm)];
assert.equal(calls.length,1,'The actual renderer argument must remain uniquely inspectable');
const argument=calls[0][1];
const MAP_WHEEL_ZOOM_ENABLED=__ENABLED__,maplibregl={},host={},pretripMapLibreRasterLayers=()=>[],state={view:{}};
const selectPretripMapLibreFeature=()=>{},hoverPretripMapLibreFeature=()=>{},hideHint=()=>{};
const options=eval('('+argument+')');
assert.equal(options.scrollZoom,MAP_WHEEL_ZOOM_ENABLED,'Canonical caller dropped wheelZoom policy');
assert.equal(options.timeoutMs,20000);
""".replace("__ENABLED__", json.dumps(enabled)))

@pytest.mark.parametrize("surface_id", ["map", "weather-map"])
def test_canonical_probe_focuses_native_canvas(surface_id):
    result = factory_replay(r"""
const selected=api.cases().find(row=>row.id===SURFACE&&row.renderer==='maplibre');
assert.ok(selected);const entry=await api.prepare(selected,{projectId:api.projectId()});
const adapter=entry.adapter,canvas=adapter.doc.querySelector('#mapLibreEvidenceMap canvas');canvas.tabIndex=0;
assert.equal(adapter.viewport,canvas,'Probe selected a non-focusable host');
adapter.viewport.focus();assert.equal(adapter.doc.activeElement,canvas);
assert.equal(adapter.gestureTarget('pan'),canvas);
await entry.dispose();console.log(JSON.stringify({canvas:true}));
""".replace("SURFACE", json.dumps(surface_id)))
    assert result["canvas"] is True

@pytest.mark.parametrize("kind", ["pan", "box-forward", "box-reverse"])
def test_production_probe_gesture_reaches_vendored_pan_and_primary_box_handlers(tmp_path, kind):
    vendor_dir = tmp_path / "vendor"
    vendor_dir.mkdir()
    for path in VENDOR.glob("*.mjs"):
        shutil.copy2(path, vendor_dir / path.name)
    module = vendor_dir / "maplibre-gl.mjs"
    original = module.read_bytes()
    with module.open("ab") as handle:
        handle.write(b"\nexport {ep as QaHandlerManager, wf as QaMousePanHandler};\n")
    assert module.read_bytes().startswith(original)
    script = (ROOT / "tests/node/map_interaction_event_regression.cjs").read_text()
    node(script.replace("__MODULE__", json.dumps(str(module))).replace("__KIND__", json.dumps(kind)))



def dashboard_replay(body):
    """Execute the production page with only network/layout test seams."""
    node(r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),{JSDOM}=require('jsdom');
const dom=new JSDOM('<body><main id="workspace"></main><div id="dashboardMapHoverHint" hidden><strong></strong><span></span></div></body>',{
 url:'http://localhost/admin/dashboard?projectId=dongqing_batongguan_historic_trail_newImport&diagnosticMapProbe=1',runScripts:'outside-only'});
const {window}=dom;window.assert=assert;window.structuredClone=structuredClone;window.matchMedia=()=>({matches:false});
window.fetch=()=>{throw Error('Network is not part of this DOM replay')};
window.Element.prototype.getBoundingClientRect=()=>({left:0,top:0,right:800,bottom:400,width:800,height:400});
// jsdom has no SVG layout; the production helper already treats a null CTM as unavailable.
window.SVGElement.prototype.getScreenCTM=()=>null;
const html=fs.readFileSync('docs/admin/scout-dashboard-v0.1.html','utf8');
const source=[...html.matchAll(/<script(?: [^>]*)?>([\s\S]*?)<\/script>/g)].map(match=>match[1]).find(script=>script.includes('const DIAGNOSTIC_MAP_PROBE'));
window.eval(source+'\nwindow.runCase=async()=>{\n'+BODY+'\n};');
window.runCase().catch(error=>{console.error(error);process.exitCode=1}).finally(()=>window.close());
""".replace("BODY", json.dumps(body)))


def terrain_setup():
    return r"""
const bounds={west:121,east:121.02,south:23.4,north:23.42};
const candidate={candidate_only:true,runtime_safety_truth:false,operational:false};
const prefix='/admin/pretrip/projects/'+encodeURIComponent(projectId());
const overlay=mode=>({mode,...candidate,bbox_wgs84:bounds,sha256:'a'.repeat(64),
 source_ref:'outputs/spatial/qgis/unit-replay/'+mode+'.png',runtime_href:prefix+'/terrain-overlays/'+mode+'.png'});
const corridor=mode=>({...overlay(mode),runtime_href:prefix+'/terrain-route-overlays/'+mode+'.png'});
const snapshot={status:'ready',project_id:projectId(),terrain_mesh:{status:'not_prepared',vertices:[],triangles:[]},
 terrain_surface:{bbox_wgs84:bounds,cell_resolution_m:20,overlays:['elevation_tint','hillshade','contours','slope_shading'].map(overlay)},
 terrain_raster_dem:{bounds_wgs84:bounds,tile_url_template:prefix+'/terrain-dem/{z}/{x}/{y}.png',minzoom:10,maxzoom:14},
 terrain_processing:{primary_processor:'qgis_processing_grass',standard_processor_completed:true,fallback_used:false,
 python_dtm_processing_used:false,local_python_comparator:'not_run'},
 terrain_structures:{status:'standard_gis_primary',points:[]},
 route_samples:{points:[{lat:23.403,lon:121.003,distance_m:0},{lat:23.417,lon:121.017,distance_m:2000}]},
 terrain_route_hypothesis:{status:'candidate_ready',candidate:'unit-route-hypothesis',
 boundary:{...candidate,authority:'candidate_only',source_type:'terrain_hypothesis',promotion_allowed:false,safe_or_walkable:'not_determined'},
 path_model:{id:'anisotropic_walk',semantics:'minimum_anisotropic_model_cost_trace'},
 display_labels:['CANDIDATE','TERRAIN HYPOTHESIS','NOT A VERIFIED TRAIL'],
 corridor:{band_model:{id:'symmetric_macro_terrain_cost',semantics:'finite_symmetric_macro_terrain_relative_cost_cell_percentile'},
 path_relationship:'separate_model_not_path_confidence_band',
 overlays:['top_5_percent_corridor','top_10_percent_corridor','top_20_percent_corridor'].map(corridor)}}};
state.navigationTerrainData=snapshot;state.navigationTerrainEvidenceDomain='terrain';state.navigationTerrainLens='structure';
const feature=(id,kind,geometry)=>({type:'Feature',geometry,properties:{id,kind,label:id,...candidate,
 project_id:projectId(),source_ref:'outputs/spatial/qgis/unit-replay/terrain_feature_stack.geojson'}});
const points=[[121.003,23.403],[121.012,23.412],[121.017,23.417]];
const features=[
 feature('ridge','qgis_candidate_ridge_line',{type:'MultiLineString',coordinates:[points]}),
 feature('valley','qgis_candidate_valley_line',{type:'LineString',coordinates:points}),
 feature('stream','qgis_candidate_stream_network',{type:'MultiLineString',coordinates:[points]}),
 feature('slope','qgis_slope_candidate',{type:'Polygon',coordinates:[[...points,points[0]]]}),
 feature('sample','qgis_terrain_feature_sample',{type:'Point',coordinates:points[1]})];
state.qgisSpatialTerrainWorkflow={project_id:projectId(),workflow_id:QGIS_NAVIGATION_PRIMARY_WORKFLOW_ID,
 state:'completed',maplibre_geojson:{type:'FeatureCollection',features}};
state.navigationTerrainLayerVisibility={candidates:true};state.qgisSpatialLayerVisibility={};
"""


@pytest.mark.parametrize("domain", ["terrain", "prior", "observed"])
def test_standard_gis_svg_draws_the_prepared_filtered_vectors_without_inventing_mesh(domain):
    dashboard_replay(terrain_setup() + r"""
state.navigationTerrainEvidenceDomain=DOMAIN;
const host=document.getElementById('workspace');host.innerHTML=renderNavigationWorkspaceMap(snapshot,null,null,null,null);
const viewport=host.querySelector('[data-dashboard-map-viewport]');
const actual=[...host.querySelectorAll('[data-navigation-qgis-feature-id]')];
assert.equal(actual.length,5,'Prepared QGIS vectors were absent from SVG fallback');
assert.deepEqual(actual.map(node=>node.dataset.navigationQgisFeatureId).sort(),qgisSpatialMaplibreFeatures().map(f=>f.properties.id).sort());
assert.equal(snapshot.terrain_mesh.status,'not_prepared');assert.equal(snapshot.terrain_mesh.triangles.length,0);
for(const node of actual){assert.equal(node.tabIndex,0);assert.equal(node.dataset.candidateOnly,'true');assert.equal(node.dataset.runtimeSafetyTruth,'false')}
assert.ok(diagnosticMapInteractionSvgVectorCount(viewport)>=5);
if(DOMAIN!=='observed'){assert.equal(host.querySelector('[data-navigation-route-path]'),null);assert.equal(host.querySelector('[data-dashboard-rudy-tile-layer]'),null)}
state.qgisSpatialLayerVisibility={ridges:false,valleys:false,streams:false,slope:false,features:false};
host.innerHTML=renderNavigationWorkspaceMap(snapshot,null,null,null,null);
assert.equal(host.querySelectorAll('[data-navigation-qgis-feature-id]').length,0,'All source layer visibility must apply');
state.qgisSpatialLayerVisibility={};state.navigationTerrainLayerVisibility={candidates:false};
host.innerHTML=renderNavigationWorkspaceMap(snapshot,null,null,null,null);assert.equal(host.querySelectorAll('[data-navigation-qgis-feature-id]').length,0);
state.navigationTerrainLayerVisibility={candidates:true};state.navigationTerrainLens='pressure';
host.innerHTML=renderNavigationWorkspaceMap(snapshot,null,null,null,null);assert.equal(host.querySelectorAll('[data-navigation-qgis-feature-id]').length,0,'Non-structure lens must retain its existing evidence scope');
state.navigationTerrainLens='structure';state.qgisSpatialTerrainWorkflow=null;state.qgisSpatialWorkflow=null;
host.innerHTML=renderNavigationWorkspaceMap(snapshot,null,null,null,null);
assert.equal(host.querySelectorAll('[data-navigation-qgis-feature-id]').length,0,'Missing data must not fabricate vectors');
""".replace("DOMAIN", json.dumps(domain)))


@pytest.mark.parametrize("mode", ["2d", "3d"])
def test_navigation_images_have_source_bound_metadata_and_keep_unapproved_images_rejected(mode):
    dashboard_replay(terrain_setup() + r"""
const mode=MODE;
for(const domain of ['observed','terrain','prior']) {
 state.navigationTerrainEvidenceDomain=domain;
 const style=navigationTerrainMapLibreStyle(snapshot,mode);
 const inventory={available:true,activeRenderer:'maplibre',sources:Object.entries(style.sources).filter(([,s])=>s.type==='image')
 .map(([id,s])=>({id,...s,layers:style.layers.filter(layer=>layer.source===id)}))};
 assert.equal(inventory.sources.length,7,'All prepared terrain and corridor images must be audited');
 const bridge={getRenderPolicySources:()=>inventory,inspectLayerOrder:()=>({layers:[]})};
 assert.equal(diagnosticMapLibreInteractionPolicy(bridge).unapprovedImageCount,0,'Prepared images lack source-bound metadata');
 for(const image of inventory.sources)for(const layer of image.layers){
  const meta=layer.metadata;assert.equal(meta['scout:source_type'],'image');
  assert.equal(meta['scout:artifact_sha256'],'a'.repeat(64));assert.ok(meta['scout:source_ref'].startsWith('outputs/spatial/qgis/'));
  assert.equal(meta['scout:candidate_only'],true);assert.equal(meta['scout:runtime_safety_truth'],false);
 }
 const saved=structuredClone(inventory.sources);
 for(const corruption of ['workspace','external','sha','ref','mode','theme','authority','missing-metadata','unregistered','unknown-family']) {
  inventory.sources=structuredClone(saved);const image=inventory.sources[0],meta=image.layers[0].metadata;
  if(corruption==='workspace')image.url=image.url.replace(projectId(),'other');
  if(corruption==='external')image.url='https://unrelated.invalid/'+image.url;
  if(corruption==='sha')meta['scout:artifact_sha256']='b'.repeat(64);
  if(corruption==='ref')meta['scout:source_ref']='';
  if(corruption==='mode')meta['scout:overlay_mode']='not-a-terrain-mode';
  if(corruption==='theme')meta['scout:single_image_theme']='rudy';
  if(corruption==='authority')meta['scout:runtime_safety_truth']=true;
  if(corruption==='missing-metadata')delete image.layers[0].metadata;
  if(corruption==='unregistered')meta['scout:layer_id']='undeclared-layer';
  if(corruption==='unknown-family')meta['scout:source_family']='undeclared-family';
  assert.ok(diagnosticMapLibreInteractionPolicy(bridge).unapprovedImageCount>0,corruption+' must remain rejected');
 }
}
""".replace("MODE", json.dumps(mode)))


@pytest.mark.parametrize("lens", ["pressure", "risk"])
def test_navigation_probe_uses_the_panel_selection_and_focusable_hint(lens):
    dashboard_replay(terrain_setup() + r"""
state.navigationTerrainEvidenceDomain='observed';state.navigationTerrainLens=LENS;
snapshot.risk_candidates={points:[{id:'risk-1',lat:23.405,lon:121.005,risk_dimensions:{teii_20m:0.4}}]};
snapshot.route_terrain_events={events:[]};
loadDataScope=async()=>{};
const originalSnapshot=navigationTerrainSnapshot;navigationTerrainSnapshot=()=>snapshot;
const choice=diagnosticMapInteractionSurfaceCases().find(row=>row.family==='navigation'&&row.renderer==='svg'&&row.variant==='observed:fallback:'+LENS);
const ready=await diagnosticPrepareMapInteractionSurface(choice,{projectId:projectId()});
try {
 assert.ok(ready.adapter,ready.detail);
 const hintTargets=ready.adapter.hintTargets();
 if(LENS==='events'&&snapshot.route_terrain_events.events.length===0)return;
 const target=hintTargets.find(node=>node.tabIndex===0);
 assert.ok(target,'The real panel selects its first point; the probe must retain that tab stop');
 target.focus();assert.equal(document.activeElement,target);
 const hint=document.getElementById('dashboardMapHoverHint');assert.equal(hint.hidden,false);
 assert.equal(target.getAttribute('aria-describedby'),hint.id);
 target.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}));assert.equal(hint.hidden,true);
}finally{await ready.dispose();navigationTerrainSnapshot=originalSnapshot}
""".replace("LENS", json.dumps(lens)))


@pytest.mark.parametrize("kind,geometry,layer_id", [
    ("qgis_candidate_ridge_line", {"type": "Point", "coordinates": [121.01, 23.41]}, "scout-qgis-ridge-candidate"),
    ("qgis_terrain_feature_sample", {"type": "LineString", "coordinates": [[121.003, 23.403], [121.017, 23.417]]}, "scout-qgis-terrain-feature-samples"),
])
def test_qgis_svg_preserves_the_registered_layer_geometry_type(kind, geometry, layer_id):
    dashboard_replay(terrain_setup() + r"""
const kind=KIND,geometry=GEOMETRY,layerId=LAYER;
const style=navigationTerrainMapLibreStyle(snapshot,'2d');
const layer=style.layers.find(value=>value.id===layerId);
assert.equal(layer.type,kind==='qgis_terrain_feature_sample'?'circle':'line');
const invalid=feature('wrong-geometry',kind,geometry);
assert.equal(renderNavigationQgisTerrainOverlay([invalid],bounds),'',
 'SVG must not draw geometry that its registered MapLibre layer cannot draw');
""".replace("KIND", json.dumps(kind)).replace("GEOMETRY", json.dumps(geometry)).replace("LAYER", json.dumps(layer_id)))


@pytest.mark.parametrize("corruption", ["source-ref", "sha-tail", "sha-and-url"])
def test_navigation_image_provenance_is_bound_to_the_selected_overlay(corruption):
    dashboard_replay(terrain_setup() + r"""
const style=navigationTerrainMapLibreStyle(snapshot,'2d');
const inventory={available:true,activeRenderer:'maplibre',sources:Object.entries(style.sources).filter(([,source])=>source.type==='image')
 .map(([id,source])=>({id,...source,layers:style.layers.filter(layer=>layer.source===id)}))};
const bridge={getRenderPolicySources:()=>inventory,inspectLayerOrder:()=>({layers:[]})};
assert.equal(diagnosticMapLibreInteractionPolicy(bridge).unapprovedImageCount,0);
const source=inventory.sources[0],metadata=source.layers[0].metadata;
const originalRef=metadata['scout:source_ref'],originalSha=metadata['scout:artifact_sha256'];
if(CORRUPTION==='source-ref')metadata['scout:source_ref']='outputs/spatial/qgis/another-valid-run/'+metadata['scout:overlay_mode']+'.png';
if(CORRUPTION==='sha-tail')metadata['scout:artifact_sha256']=originalSha.slice(0,16)+'b'.repeat(48);
if(CORRUPTION==='sha-and-url') {
 metadata['scout:artifact_sha256']='c'.repeat(64);
 const url=new URL(source.url,location.href);url.searchParams.set('v','c'.repeat(16));source.url=url.href;
}
assert.equal(navigationTerrainImageLayerMetadata(snapshot,metadata['scout:layer_id'])['scout:source_ref'],originalRef);
assert.equal(navigationTerrainImageLayerMetadata(snapshot,metadata['scout:layer_id'])['scout:artifact_sha256'],originalSha);
assert.equal(diagnosticMapLibreInteractionPolicy(bridge).unapprovedImageCount,1,
 'A valid-looking source reference and SHA must match the actual selected overlay, not just their syntax');
""".replace("CORRUPTION", json.dumps(corruption)))


@pytest.mark.parametrize("kind", ["unregistered-kind", "__proto__", "constructor"])
def test_qgis_svg_ignores_unregistered_feature_kinds(kind):
    dashboard_replay(terrain_setup() + r"""
const invalid=feature('unregistered',KIND,{type:'LineString',coordinates:points});
assert.equal(renderNavigationQgisTerrainOverlay([invalid],bounds),'',
 'Unknown QGIS kinds must not become visible evidence through inherited object properties');
""".replace("KIND", json.dumps(kind)))
