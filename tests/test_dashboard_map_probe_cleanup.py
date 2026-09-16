"""Replay real Diagnostic entry cleanup with bounded renderer/IO DOM fixtures."""

import hashlib
import json
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "docs/admin/scout-dashboard-v0.1.html"


@pytest.fixture(scope="module", autouse=True)
def _receipt(record_testsuite_property):
    record_testsuite_property("dashboard_source_sha256", hashlib.sha256(PAGE.read_bytes()).hexdigest())


def _run(body):
    setup = r'''
const assert=require('node:assert/strict'),fs=require('node:fs'),{JSDOM}=require('jsdom');
const html=fs.readFileSync('docs/admin/scout-dashboard-v0.1.html','utf8');
const dom=new JSDOM('<body><main id="workspace"></main></body>',{url:'http://localhost/admin/dashboard?projectId=selected&diagnosticMapProbe=1',runScripts:'outside-only'});
const {window}=dom,children=[];
window.AbortController=AbortController;window.AbortSignal=AbortSignal;
window.__child=href=>{
  const child=new JSDOM('<body><svg id="map"><g data-layer-group="rudy-twmap"><image data-raster-tile="14/1/1"/></g></svg><button id="zoomIn"></button><select data-cwa-imagery-product><option value="radar-a">radar</option><option value="satellite-a">satellite</option></select><select data-cwa-imagery-window><option value="12h">12h</option></select><input data-cwa-imagery-timeline max="1" value="0"><input data-cwa-imagery-opacity="radar" value="70"><input data-cwa-imagery-opacity="satellite" value="80"></body>',{url:href,runScripts:'outside-only'}).window;
  Object.defineProperty(child.document,'readyState',{value:'complete',configurable:true});children.push(child);return child;
};
const names=['diagnosticMapCleanupComplete','diagnosticMapCleanupResult','diagnosticWithMapCleanup',
  'diagnosticDisposeEmbeddedMapFrame','diagnosticDisposeNavigationMaps','diagnosticDisposeRudyProbe','diagnosticMapInteractionFrameContext',
  'diagnosticProbeEmbeddedMapOrder','diagnosticProbeNavigationMapOrder',
  'navigationTerrainWorkspaceSelection','navigationTerrainPressureSamples',
  'diagnosticWeatherLiveFrames','diagnosticWeatherLiveTiles','destroyNavigationTerrainMapLibre'];
const source=names.map(name=>{const match=html.match(new RegExp('^    (?:async )?function '+name+'\\([\\s\\S]*?^    }','m'));assert.ok(match,name);return match[0]}).join('\n');
window.eval(source+String.raw`
const location=window.location,projectId=()=> 'selected',surfaceSrc=path=>path+'?projectId=selected';
const asArray=value=>Array.isArray(value)?value:[];
const state={navigationTerrainEvidenceDomain:'observed',navigationTerrainLens:'structure'};
const navigationTerrainMapLibreRuntime={maps:[],generation:0,cameraByMode:{},pendingInitializations:new Set(),initializationStarted:0,initializationSettled:0};
const options={},calls=[],created=[];
const clean=()=>({disposed:true,activeMaps:0,pendingInitializations:0,errors:[]});
const diagnosticRequire=(condition,message)=>{if(!condition)throw Error(message)};
const diagnosticSafeDetail=value=>String(value);
const diagnosticWarning=(detail,dataStatus)=>({status:'warning',detail,dataStatus});
const diagnosticAvailability=(dataStatus,detail)=>({status:'passed',dataStatus,detail});
const diagnosticMapOrderGap=(surface,variant,detail)=>({...surface,variant,status:'warning',layers:[],violations:[],gaps:[detail]});
const diagnosticMarkupRoot=markup=>{const template=document.createElement('template');template.innerHTML=markup;return template.content};
const renderWeatherIntersectionMap=()=>'<iframe src="/admin/pretrip?projectId=selected"></iframe>';
const weatherCandidateSnapshot=()=>({});
const bindWeatherCwaMapFrame=()=>{},bindPretripMapOnlyFrame=()=>{};
const WEATHER_EMBEDDED_MAP_LAYER_IDS=['rudy-twmap','cwa-weather','route','segments','checkpoints'];
const diagnosticProbeDebugSplitControls=async()=>[];
const loadDataScope=async()=>{},stopNavigationTerrainPolling=()=>calls.push('stop-polling');
const navigationTerrainSnapshot=()=>({}),navigationTerrainFeatures=()=>[];
const renderNavigationTerrainMapLibreHost=(_snapshot,mode)=>'<div data-mode="'+mode+'"><canvas></canvas></div>';
const renderNavigationWorkspaceMap=()=>'<svg/>',renderNavigationTerrainMesh=()=>'<svg/>',renderNavigationTerrainMap=()=>'<svg/>';
const diagnosticInspectMapOrderRoot=(_root,surface,variant)=>[{...surface,variant,status:'passed',layers:[],violations:[],gaps:[]}];
const rememberNavigationTerrainMapLibreCamera=()=>{};
const order=()=>({status:options.orderFailure?'failed':'passed',layers:[{id:'route'}],violations:options.orderFailure?[{code:'background_over_route'}]:[],gaps:[]});
window.ScoutMapLibreEvidence={inspectMapLibreLayerOrder:order};
async function initializeNavigationTerrainMapLibre(){
  navigationTerrainMapLibreRuntime.initializationStarted++;
  for(const host of document.querySelectorAll('[data-mode]')){
    const canvas=host.querySelector('canvas'),mode=host.dataset.mode;
    host.dataset.navigationMaplibreStatus='ready';
    const transport={destroyed:false,controllers:new Set([1]),destroy(){if(options.transportFailure)throw Error('fixture transport failure');this.destroyed=true;this.controllers.clear();calls.push('transport-remove:'+mode)}};
    const map={getCanvas:()=>canvas,getStyle:()=>({layers:[{id:'route'}]}),remove(){calls.push('map-remove:'+mode);canvas.remove()}};
    const entry={host,map,mode,rudyTransport:transport};created.push(entry);navigationTerrainMapLibreRuntime.maps.push(entry);
  }
  navigationTerrainMapLibreRuntime.initializationSettled++;
}
const frames=['radar','satellite'].flatMap(family=>[0,1].map(index=>({family,productId:family+'-a',frameId:family+'-'+index,
  assetHref:'http://localhost/admin/pretrip/projects/selected/weather-imagery/'+family+'-'+index+'.png'})));
const diagnosticCoverageRead=async()=>({available:true,data:{}}),diagnosticWeatherCachedFrames=()=>frames;
window.fetch=async()=>({ok:true,blob:async()=>({})});
window.createImageBitmap=async()=>({width:10,height:10,close:()=>calls.push('bitmap-close')});
const diagnosticWeatherTileSnapshot=()=>({matrix:options.matrix,status:'ready',generation:String(options.matrix),failure:null});
const diagnosticWeatherValidateTileUrls=()=>['http://localhost/admin/tiles/imagery/selected/rudy-twmap/15/1/1.png?cache_only=1'];
function bindFrame(frame){
  if(frame.fixtureBound)return;frame.fixtureBound=true;
  const child=window.__child(frame.src),doc=child.document;
  Object.defineProperty(frame,'contentWindow',{value:child,configurable:true});Object.defineProperty(frame,'contentDocument',{value:doc,configurable:true});
  const remove=frame.remove.bind(frame);frame.remove=()=>{calls.push('frame-remove');remove()};
  frame.dashboardMapWeatherAvailabilityObserver={disconnect(){calls.push('observer-disconnect');if(options.observerFailure)throw Error('fixture observer failure')}};
  const renderer=new URL(frame.src).searchParams.get('mapRenderer')||'svg';
  const bridge={inspectLayerOrder:()=>({...order(),projectId:'selected',rendererState:'ready',activeRenderer:renderer}),
    async dispose(){calls.push('dispose-start');await Promise.resolve();calls.push('dispose-end');if(options.disposeThrow)throw Error('fixture dispose failure');return options.incomplete?{disposed:false,activeMaps:1,pendingInitializations:1,errors:['fixture leak']}:clean()}};
  child.scoutPretripMapRendererBridge=bridge;child.scoutDebugMapRendererBridge=bridge;child.scoutDashboardDiagnostics=bridge;
  child.scoutPretripProjectBridge={getSnapshot:()=>({status:'base_ready'})};
  options.matrix=14;doc.getElementById('zoomIn').addEventListener('click',()=>{options.matrix++});
  const current={windowId:'12h',productId:'radar-a',frameIndex:0,radarOpacityPercent:70,satelliteOpacityPercent:80,layerEnabled:true};
  function update(){
    const frame=frames.find(item=>item.productId===current.productId&&item.frameId===current.productId.replace('-a','')+'-'+current.frameIndex);
    let image=doc.querySelector('image[data-cwa-imagery-family="'+frame.family+'"]');
    if(!image){image=doc.createElementNS('http://www.w3.org/2000/svg','image');image.dataset.cwaImageryFamily=frame.family;doc.getElementById('map').append(image)}
    image.dataset.cwaImageryFrame=frame.frameId;image.setAttribute('href',frame.assetHref);image.setAttribute('opacity',current[frame.family+'OpacityPercent']/100);
  }
  child.scoutCwaImageryController={getState:()=>({...current,products:['radar-a','satellite-a'],boundary:{cacheOnly:true,candidateOnly:true},current:{frameId:current.productId.replace('-a','')+'-'+current.frameIndex}})};
  for(const [selector,event,key] of [['[data-cwa-imagery-window]','change','windowId'],['[data-cwa-imagery-product]','change','productId'],['[data-cwa-imagery-timeline]','input','frameIndex'],['[data-cwa-imagery-opacity="radar"]','input','radarOpacityPercent'],['[data-cwa-imagery-opacity="satellite"]','input','satelliteOpacityPercent']]){
    doc.querySelector(selector).addEventListener(event,e=>{current[key]=key.endsWith('Id')?e.target.value:Number(e.target.value);if(key==='productId')current.frameIndex=0;update()});
  }
  update();
}
async function diagnosticWaitForMapOrder(read){
  document.querySelectorAll('iframe').forEach(bindFrame);
  if(options.waitFailure)throw Error('fixture not ready');
  const value=read();if(!value)throw Error('fixture unavailable');return value;
}
window.api={options,calls,created,clean,root:document.getElementById('workspace'),bindFrame,
  disposeFrame:diagnosticDisposeEmbeddedMapFrame,withCleanup:diagnosticWithMapCleanup,
  disposeNavigation:diagnosticDisposeNavigationMaps,disposeRudy:diagnosticDisposeRudyProbe,
  runtime:navigationTerrainMapLibreRuntime,initializeNavigation:initializeNavigationTerrainMapLibre,
  embedded:diagnosticProbeEmbeddedMapOrder,navigation:diagnosticProbeNavigationMapOrder,
  weatherTiles:diagnosticWeatherLiveTiles,weatherFrames:diagnosticWeatherLiveFrames};
`);
const {api}=window;
'''
    script = setup + "\n(async()=>{\n" + body + r'''
})().catch(error=>{console.error(error);process.exitCode=1}).finally(()=>{for(const child of children)child.close();window.close()});
'''
    result = subprocess.run(["node", "-e", script], cwd=ROOT, text=True, capture_output=True, timeout=35)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_cleanup_failure_preserves_existing_failed_layer_evidence_and_original_exception():
    result = _run(r'''
const rows=[{status:'passed',layers:[{id:'route'}],violations:[],gaps:[]},{status:'failed',layers:[{id:'radar'}],violations:[{code:'wrong-order'}],gaps:[]}];
const bad={disposed:false,activeMaps:1,pendingInitializations:1,errors:['not removed']};
const output=await api.withCleanup(async()=>rows,async()=>bad);
assert.deepEqual(output.map(row=>row.status),['warning','failed']);assert.deepEqual(output[1].violations,rows[1].violations);
assert.deepEqual(output[0].layers,rows[0].layers);assert.equal(rows[0].status,'passed');
let error;try{await api.withCleanup(async()=>{throw Error('original renderer failure')},async()=>bad)}catch(caught){error=caught}
assert.equal(error.message,'original renderer failure');assert.equal(error.cleanupReceipt,bad);
console.log(JSON.stringify({preserved:true}));
''')
    assert result["preserved"]


@pytest.mark.parametrize("entry", ["/admin/pretrip", "/admin/debug", "/admin/dashboard"])
def test_frame_disposal_waits_for_bridge_before_removing_frame(entry):
    result = _run("""
const frame=window.document.createElement('iframe');frame.src=%s;api.root.append(frame);api.bindFrame(frame);
const receipt=await api.disposeFrame(frame);assert.equal(receipt.disposed,true);assert.equal(frame.isConnected,false);
assert.ok(api.calls.indexOf('dispose-end')<api.calls.indexOf('frame-remove'));
console.log(JSON.stringify({disposed:receipt.disposed}));
""" % json.dumps("http://localhost" + entry + "?projectId=selected"))
    assert result["disposed"]


@pytest.mark.parametrize("failure", ["incomplete", "disposeThrow", "observerFailure"])
def test_failed_cleanup_is_reported_and_frame_removal_is_still_attempted(failure):
    result = _run("""
api.options[%s]=true;
const frame=window.document.createElement('iframe');frame.src='/admin/pretrip?projectId=selected';api.root.append(frame);api.bindFrame(frame);
const receipt=await api.disposeFrame(frame);assert.equal(receipt.disposed,false);assert.equal(frame.isConnected,false);assert.ok(receipt.errors.length);
console.log(JSON.stringify({failed:true}));
""" % json.dumps(failure))
    assert result["failed"]


def test_d044_six_canonical_entry_renderers_dispose_after_retaining_order_rows():
    result = _run(r'''
let count=0;
for(const id of ['map','weather-map','debug-map'])for(const renderer of ['svg','maplibre']){
  api.calls.length=0;const rows=await api.embedded(api.root,{id,label:id},renderer);
  assert.equal(rows.length,2);for(const row of rows){assert.equal(row.status,'passed');assert.equal(row.cleanupStatus,'passed');assert.equal(row.layers[0].id,'route')}
  assert.ok(api.calls.indexOf('dispose-end')<api.calls.indexOf('frame-remove'));assert.equal(window.document.querySelector('iframe'),null);count++;
}
console.log(JSON.stringify({cases:count}));
''')
    assert result["cases"] == 6


def test_d044_canonical_cleanup_failure_does_not_overwrite_existing_order_violation():
    result = _run(r'''
api.options.orderFailure=true;api.options.incomplete=true;
const rows=await api.embedded(api.root,{id:'map',label:'Main'},'maplibre');
assert.equal(rows.length,2);for(const row of rows){assert.equal(row.status,'failed');assert.equal(row.cleanupStatus,'warning');assert.equal(row.violations[0].code,'background_over_route')}
console.log(JSON.stringify({retained:true}));
''')
    assert result["retained"]


@pytest.mark.parametrize("failure", [False, True])
def test_d044_navigation_all_domains_collect_real_teardown_receipts(failure):
    result = _run("""
api.options.transportFailure=%s;
const rows=await api.navigation(api.root,{id:'navigation-map',label:'Nav'});
const maps=rows.filter(row=>row.variant.includes('MapLibre'));assert.equal(maps.length,6);assert.equal(api.created.length,6);
for(const row of maps){assert.equal(row.status,%s);assert.equal(row.cleanupStatus,%s);assert.equal(row.layers[0].id,'route')}
if(!api.options.transportFailure){assert.equal(api.calls.filter(item=>item.startsWith('map-remove:')).length,6);assert.equal(api.calls.filter(item=>item.startsWith('transport-remove:')).length,6)}
console.log(JSON.stringify({cases:maps.length}));
""" % (json.dumps(failure), json.dumps("warning" if failure else "passed"), json.dumps("warning" if failure else "passed")))
    assert result["cases"] == 6


@pytest.mark.parametrize("method", ["weatherTiles", "weatherFrames"])
@pytest.mark.parametrize("unavailable", [False, True])
def test_d037_old_weather_probe_success_and_unavailable_both_await_cleanup(method, unavailable):
    result = _run("""
api.options.waitFailure=%s;
const result=await api[%s]();assert.equal(result.status,%s);assert.equal(result.cleanupStatus,'passed');
assert.ok(api.calls.indexOf('dispose-end')<api.calls.indexOf('frame-remove'));assert.equal(window.document.querySelector('iframe'),null);
console.log(JSON.stringify({status:result.status,cleanup:result.cleanupStatus,decoded:api.calls.filter(item=>item==='bitmap-close').length}));
""" % (json.dumps(unavailable), json.dumps(method), json.dumps("warning" if unavailable else "passed")))
    assert result["cleanup"] == "passed"
    if not unavailable:
        assert result["decoded"] >= 1


def test_d037_borrowed_weather_frame_is_restored_without_destroying_its_owner():
    result = _run(r'''
const frame=window.document.createElement('iframe');frame.src='/admin/pretrip?projectId=selected';api.root.append(frame);api.bindFrame(frame);
const before=JSON.stringify(frame.contentWindow.scoutCwaImageryController.getState());
const result=await api.weatherFrames(frame);assert.equal(result.status,'passed');assert.equal(frame.isConnected,true);
assert.equal(api.calls.includes('dispose-start'),false);assert.equal(JSON.stringify(frame.contentWindow.scoutCwaImageryController.getState()),before);
await api.disposeFrame(frame);console.log(JSON.stringify({restored:true}));
''')
    assert result["restored"]


@pytest.mark.parametrize("entry", ["disposeNavigation", "disposeRudy"])
def test_navigation_dispose_awaits_inflight_initialization_and_removes_late_map(entry):
    result = _run(r'''
let release;const lifetime=new Promise(resolve=>{release=resolve});
api.runtime.pendingInitializations.add(lifetime);api.runtime.initializationStarted++;
const closing=api[ENTRY]();let done=false;closing.then(()=>{done=true});await Promise.resolve();assert.equal(done,false);
api.root.innerHTML='<div data-mode="2d"><canvas></canvas></div>';
await api.initializeNavigation();const late=api.created.at(-1);assert.equal(late.map.getCanvas().isConnected,true);
api.runtime.pendingInitializations.delete(lifetime);api.runtime.initializationSettled++;release();
const outer=await closing;assert.equal(outer.disposed,true);assert.equal(outer.pendingInitializations,0);
const receipt=outer.initializationEvidence?outer:outer.children.find(child=>child.entry==='navigation').receipt;
assert.equal(late.map.getCanvas().isConnected,false);assert.equal(late.rudyTransport.destroyed,true);
assert.equal(receipt.initializationEvidence.pendingBefore,1);assert.equal(receipt.initializationEvidence.pendingAfter,0);
assert.equal(receipt.initializationEvidence.awaited,1);assert.ok(receipt.initializationEvidence.generationAfter>receipt.initializationEvidence.generationBefore);
console.log(JSON.stringify({awaited:true,lateRemoved:true}));
'''.replace("ENTRY", json.dumps(entry)))
    assert result == {"awaited": True, "lateRemoved": True}


def test_navigation_stale_settlement_accounting_cannot_report_pending_zero():
    result = _run(r'''
api.runtime.pendingInitializations.add(Promise.resolve());api.runtime.initializationStarted++;
const receipt=await api.disposeNavigation();assert.equal(receipt.disposed,false);assert.equal(receipt.pendingInitializations,null);
assert.equal(receipt.initializationEvidence.pendingAfter,1);
assert.ok(receipt.errors.some(error=>error.errorName==='SettledInitializationStillTracked'));
console.log(JSON.stringify({detected:true}));
''')
    assert result["detected"]


def test_successful_outer_cleanup_does_not_hide_incomplete_inner_cleanup():
    result = _run(r'''
const bad={disposed:false,activeMaps:1,pendingInitializations:0,errors:['inner leak']};
const report=await api.withCleanup(async()=>({status:'warning',cleanup:bad,layers:[{id:'route'}]}),async()=>api.clean());
assert.equal(report.cleanupStatus,'warning');assert.equal(report.cleanup.children[0],bad);assert.equal(report.layers[0].id,'route');
let error;try{await api.withCleanup(async()=>{throw Object.assign(Error('inner failure'),{cleanupReceipt:bad})},async()=>api.clean())}catch(caught){error=caught}
assert.equal(error.message,'inner failure');assert.equal(error.cleanupReceipt.disposed,false);assert.equal(error.cleanupReceipt.children[0],bad);
console.log(JSON.stringify({preserved:true}));
''')
    assert result["preserved"]


def test_navigation_cleanup_continues_after_each_release_error_and_keeps_receipt():
    result = _run(r'''
api.root.innerHTML='<div data-mode="2d"><canvas></canvas></div>';
await api.initializeNavigation();const entry=api.created.at(-1);
entry.routeAnnotations=[{remove(){api.calls.push('annotation-1');throw Error('annotation failure')}},
  {remove(){api.calls.push('annotation-2')}}];
entry.evidenceControlsCleanup=()=>{api.calls.push('controls');throw TypeError('controls failure')};
api.options.transportFailure=true;
const receipt=await api.disposeNavigation();assert.equal(receipt.disposed,false);
assert.equal(entry.map.getCanvas().isConnected,false);assert.equal(entry.mapDisposeReceipt.mapRemoved,true);
assert.ok(api.calls.includes('annotation-2'));assert.ok(api.calls.includes('map-remove:2d'));
for(const phase of ['route-annotation-0','evidence-controls','tile-transport'])assert.ok(receipt.errors.some(error=>error.phase===phase));
console.log(JSON.stringify({allReleasesAttempted:true,errorsRetained:true}));
''')
    assert result == {"allReleasesAttempted": True, "errorsRetained": True}


def test_detached_canvas_does_not_hide_failed_map_remove():
    result = _run(r'''
api.root.innerHTML='<div data-mode="2d"><canvas></canvas></div>';
await api.initializeNavigation();const entry=api.created.at(-1);entry.map.getCanvas().remove();
entry.map.remove=()=>{throw Error('map resource release failed')};
const receipt=await api.disposeNavigation();assert.equal(receipt.disposed,false);
assert.equal(entry.mapDisposeReceipt.mapRemoved,false);assert.equal(receipt.pendingInitializations,null);
assert.ok(receipt.errors.some(error=>error.phase==='map-remove'));
assert.ok(receipt.errors.some(error=>error.errorName==='MissingMapRemoveReceipt'));
console.log(JSON.stringify({detected:true}));
''')
    assert result["detected"]
