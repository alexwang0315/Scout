"""Replay the Diagnostic production-entry factory's isolation and lifecycle.

Data loading and renderer construction use bounded DOM fixtures. The real
factory, frame readiness, adapter selectors, and cancellation helper execute;
this proves orchestration, not browser rendering or the D026–D029 verdicts.
"""

import hashlib
import json
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "docs/admin/scout-dashboard-v0.1.html"


@pytest.fixture(scope="module", autouse=True)
def _source_receipt(record_testsuite_property):
    record_testsuite_property("dashboard_source_sha256", hashlib.sha256(PAGE.read_bytes()).hexdigest())


def _run(body):
    setup = r"""
const assert = require('node:assert/strict'), fs = require('node:fs'), {JSDOM} = require('jsdom');
const html = fs.readFileSync('docs/admin/scout-dashboard-v0.1.html', 'utf8');
const dom = new JSDOM('<body><button id="outside">untouched</button><main id="workspace"></main></body>', {
  url:'http://localhost/admin/dashboard?projectId=dongqing_batongguan_historic_trail_newImport&diagnosticMapProbe=1',
  runScripts:'outside-only',
});
const {window} = dom;
const childWindows = [];
window.fetch = () => {throw Error('Unexpected network access')};
window.__child = href => {
  const child = new JSDOM('<body><svg id="map" viewBox="10 20 500 300"><circle data-evidence-type="checkpoint" data-source-id="svg-source" tabindex="0"/></svg><div id="mapLibreEvidenceMap"><canvas></canvas></div><div id="hoverHint" class="is-hidden"></div><button id="zoomIn"></button><button id="zoomOut"></button><button id="fitRoute"></button><button id="panMode"></button><button id="boxZoomMode"></button></body>', {url:href,runScripts:'outside-only'}).window;
  Object.defineProperty(child.document,'readyState',{value:'complete',configurable:true});
  childWindows.push(child); return child;
};
function source(name) {
  const found = html.match(new RegExp('^    (?:async )?function '+name+'\\([\\s\\S]*?^    }','m'));
  assert.ok(found,'Missing production function '+name); return found[0];
}
const registry = html.match(/^    const DASHBOARD_MAP_SURFACES = Object.freeze\(\[[\s\S]*?^    \]\);/m)[0];
const names = ['diagnosticMapInteractionSurfaceCases','diagnosticMapInteractionFrameContext',
  'diagnosticMapInteractionNodeVisible','diagnosticMapInteractionSvgVectorCount','diagnosticMapInteractionNavigationState',
  'diagnosticPretripMapInteractionAdapter','diagnosticNavigationMapInteractionAdapter',
  'diagnosticPrepareMapInteractionSurface','discardDashboardPendingRudyTileGeneration'];
window.eval(registry+'\n'+names.map(source).join('\n')+String.raw`
const DIAGNOSTIC_MAP_PROBE = true;
const state = {route:'diagnostic',architectureLens:'original-architecture',navigationTerrainLens:'original-navigation',
  navigationTerrainEvidenceDomain:'original-domain',mapViewportById:{original:{zoom:2}}};
const navigationTerrainMapLibreRuntime = {maps:[],generation:0,cameraByMode:{}};
const NAVIGATION_RUDY_TILE_SOURCE = {cacheLayerId:'imagery'};
const asArray = value => Array.isArray(value) ? value : [];
const diagnosticRequire = (condition,message) => {if(!condition) throw Error(message)};
const projectId = () => new URLSearchParams(location.search).get('projectId');
const surfaceSrc = path => path+'?projectId='+encodeURIComponent(projectId());
const calls = [];
const options = {};
const cleanReceipt = () => ({disposed:true,activeMaps:0,pendingInitializations:0,errors:[]});
const markup = (name, domain='', loading=false) => '<section data-fixture-renderer="'+name+'"><div data-dashboard-map-viewport="'+name+'" '
  +(loading ? 'data-navigation-evidence-state="loading"' : domain ? 'data-navigation-evidence-domain="'+(options.actualDomain || domain)+'"' : '')
  +'><button data-map-rudy-updates aria-pressed="true"></button><svg>'
  +(!domain || domain==='observed' || loading ? '<g data-dashboard-rudy-tile-layer="true"></g>' : '')+'</svg></div></section>';
function loadDataScope(scope) {calls.push(['load',scope]);return Promise.resolve()}
function stopNavigationTerrainPolling() {calls.push(['stop-polling'])}
function navigationTerrainSnapshot() {return {source:'recorded-snapshot'}}
function architectureSnapshot() {return {source:'recorded-architecture'}}
function weatherCandidateSnapshot() {return {source:'recorded-weather'}}
function renderMapPanel(mode) {calls.push(['render-panel',mode]);return markup(mode)}
function renderPaceFitPrimaryMap() {calls.push(['render-pace']);return markup('pace-fit')}
function renderArchitectureMap(snapshot) {calls.push(['render-architecture',state.architectureLens,snapshot.source]);return markup('architecture')}
function renderNavigationWorkspaceMap(snapshot) {calls.push(['render-fallback',state.navigationTerrainEvidenceDomain,state.navigationTerrainLens,snapshot.source]);return markup('navigation-fallback',state.navigationTerrainEvidenceDomain)}
function renderNavigationWorkspaceLoading(snapshot) {calls.push(['render-loading',state.navigationTerrainEvidenceDomain,state.navigationTerrainLens,snapshot.source]);return markup('navigation-loading',state.navigationTerrainEvidenceDomain,true)}
function renderNavigationTerrainMapLibreHost(snapshot,mode) {
  calls.push(['render-navigation-maplibre',state.navigationTerrainEvidenceDomain,mode,state.navigationTerrainLens]);
  return '<section data-navigation-maplibre-shell="'+mode+'"><div data-navigation-maplibre-map="'+mode+'" data-navigation-evidence-domain="'
    +(options.actualDomain || state.navigationTerrainEvidenceDomain)+'" data-navigation-terrain-lens="'+state.navigationTerrainLens+'"><canvas tabindex="0"></canvas><button class="maplibregl-ctrl-zoom-in"></button><button class="maplibregl-ctrl-zoom-out"></button></div><button data-navigation-maplibre-fit="'+mode+'"></button></section>';
}
function navigationTerrainRudyTileTemplate() {
  return options.template || '/admin/tiles/imagery/'+projectId()+'/imagery/{z}/{x}/{y}.png?source_id=happyman_rudy_twmap&cache_only=1&exact=1';
}
async function initializeNavigationTerrainMapLibre() {
  calls.push(['init-navigation']);
  if (options.initFailure) throw Error('Fixture renderer initialization failed');
  const host=document.querySelector('[data-navigation-maplibre-map]');
  const mode=host.dataset.navigationMaplibreMap;
  const rudyTransport={destroyed:false,controllers:new Set([{}]),destroy(){this.destroyed=true;this.controllers.clear()}};
  const map={getCanvas:()=>host.querySelector('canvas'),isStyleLoaded:()=>true,
    getCenter:()=>({lng:121,lat:23.5}),getZoom:()=>14,dragPan:{isEnabled:()=>true},
    remove(){if(!options.leakCanvas) host.querySelector('canvas').remove()}};
  navigationTerrainMapLibreRuntime.maps.push({host,map,mode,rudyTransport});
}
function destroyNavigationTerrainMapLibre() {
  calls.push(['destroy-navigation']);navigationTerrainMapLibreRuntime.generation++;
  for(const entry of navigationTerrainMapLibreRuntime.maps.splice(0)) {
    if(!options.leakTransport) entry.rudyTransport.destroy();entry.map.remove();
  }
}
function renderWeatherIntersectionMap(snapshot) {
  calls.push(['render-weather',snapshot.source]);
  return '<div><iframe src="/admin/pretrip?projectId='+projectId()+'"></iframe></div>';
}
function diagnosticMarkupRoot(markup) {const root=document.createElement('div');root.innerHTML=markup;return root}
function bindWeatherCwaMapFrame(frame) {calls.push(['bind-weather',frame.src])}
function bindPretripMapOnlyFrame(frame) {calls.push(['bind-main',frame.src])}
function diagnosticSetMapInteractionCacheOnly(root) {
  calls.push(['cache-only']);
  for(const viewport of root.querySelectorAll('[data-dashboard-map-viewport]')) {
    assertNoBound(viewport);viewport.dataset.mapRudyUpdates='false';
  }
}
function assertNoBound(viewport) {if(viewport.dashboardMapController) throw Error('Bound before cache-only')}
function bindDashboardMapHints() {calls.push(['bind-hints'])}
function bindDashboardMapViewports() {
  calls.push(['bind-viewports']);
  for(const viewport of document.querySelectorAll('[data-dashboard-map-viewport]')) {
    if(viewport.dataset.mapRudyUpdates!=='false') throw Error('Renderer escaped cache-only before binding');
    viewport.dashboardMapController={getState:()=>({zoom:1,x:0,y:0})};
    const layer=viewport.querySelector('[data-dashboard-rudy-tile-layer]');
    if(!layer) continue;
    layer.dataset.dashboardRudyPendingTileKey='pending-native-cohort-fixture';
    const pending=document.createElementNS('http://www.w3.org/2000/svg','g');
    pending.dataset.dashboardRudyTileGeneration='pending';
    pending.innerHTML='<image href="/admin/tiles/cache-only-fixture.png"/>';
    if(!options.missingCancel) pending.cancelRudyGeneration=()=>calls.push(['cancel-svg-generation']);
    layer.append(pending);
  }
}
function diagnosticSharedMapInteractionAdapter(viewport) {return {doc:document,viewport,camera:()=>viewport.dashboardMapController.getState()}}
function diagnosticMapLibreInteractionPolicy(bridge) {return bridge.getRenderPolicySources?.() || {unapprovedImageCount:null}}
function diagnosticDebugMapImageApproved(image) {return image.hasAttribute('data-raster-tile')}
window.ScoutMapLibreEvidence={inspectMapLibreLayerOrder:()=>({layers:[]}),
  inspectRasterRenderPolicySources:(_map,transport)=>({available:Boolean(transport),sources:[]})};
async function diagnosticWaitForMapOrder(read) {
  const frame=document.querySelector('iframe');
  if(!frame) {const result=read();if(!result) throw Error('Fixture renderer unavailable');return result}
  // A newly appended frame may expose no root, or its old about:blank document.
  Object.defineProperty(frame,'contentDocument',{value:{documentElement:null},configurable:true});
  if(read()) throw Error('Null document root accepted');
  const child=window.__child(frame.src);
  const requested=new URL(frame.src).searchParams.get('mapRenderer');
  const actual=options.actualRenderer || requested;
  child.document.getElementById('map').hidden=actual!=='svg';
  child.document.getElementById('mapLibreEvidenceMap').hidden=actual!=='maplibre';
  child.scoutPretripMapRendererBridge={getSnapshot:()=>({zoom:14,center:[121,23.5]}),
    inspectLayerOrder:()=>({layers:[{id:'route'}],projectId:projectId(),rendererState:'ready',activeRenderer:actual}),
    getRenderPolicySources:()=>({available:true,activeRenderer:actual,sources:[]}),
    dispose:async()=>{calls.push(['dispose-canonical']);return options.childReceipt || cleanReceipt()}};
  child.scoutPretripProjectBridge={getSnapshot:()=>({status:'base_ready'})};
  Object.defineProperty(frame,'contentDocument',{value:child.document,configurable:true});
  Object.defineProperty(frame,'contentWindow',{value:child,configurable:true});
  const result=read();if(!result) throw Error('Fixture final document rejected');return result;
}
window.api={cases:diagnosticMapInteractionSurfaceCases,frameContext:diagnosticMapInteractionFrameContext,
  prepare:diagnosticPrepareMapInteractionSurface,pretripAdapter:diagnosticPretripMapInteractionAdapter,
  navAdapter:diagnosticNavigationMapInteractionAdapter,state,options,calls,runtime:navigationTerrainMapLibreRuntime,
  registry:DASHBOARD_MAP_SURFACES,projectId};
`);
const {api} = window;
"""
    script = setup + "\n(async()=>{\n" + body + r"""
})().catch(error=>{console.error(error);process.exitCode=1}).finally(()=>{
  for(const child of childWindows) child.close();window.close();
});
"""
    result = subprocess.run(["node", "-e", script], cwd=ROOT, text=True, capture_output=True, timeout=35)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_case_inventory_retains_every_original_renderer_and_lens():
    result = _run(r"""
const cases=api.cases();
assert.equal(cases.length,40);assert.equal(new Set(cases.map(item=>item.key)).size,40);
assert.equal(new Set(cases.map(item=>item.id)).size,9);
assert.equal(cases.filter(item=>item.family==='navigation').length,24);
assert.equal(cases.filter(item=>item.family==='architecture').length,7);
assert.ok(cases.some(item=>item.family==='architecture' && item.variant==='time_window'));
for(const domain of ['observed','terrain','prior']) {
  const domainCases=cases.filter(item=>item.domain===domain);
  assert.equal(domainCases.length,domain==='observed'?16:4);
  for(const item of domainCases) {
    const [actualDomain,mode,lens]=item.variant.split(':');
    assert.equal(actualDomain,domain);
    if(domain!=='observed')assert.equal(lens,'structure','Unreachable non-observed lens fabricated');
    assert.ok(['2d','3d','fallback','loading'].includes(mode));
  }
  assert.ok(domainCases.some(item=>item.variant===domain+':loading:structure'));
}
assert.equal(cases.filter(item=>item.family==='canonical-pretrip').length,4);
api.registry[0].family='canonical-pretrip';
assert.throws(()=>api.cases(),/denominators/);
console.log(JSON.stringify({cases:cases.length,ids:new Set(cases.map(item=>item.id)).size}));
""")
    assert result == {"cases": 40, "ids": 9}


def test_frame_readiness_rejects_null_loading_old_and_mixed_documents():
    result = _run(r"""
const expected='http://localhost/admin/pretrip?projectId=correct&mapRenderer=svg';
const child=window.__child(expected), doc=child.document;
assert.equal(api.frameContext({contentDocument:{documentElement:null},contentWindow:child},expected),null);
assert.equal(api.frameContext({contentDocument:doc,contentWindow:window},expected),null);
assert.equal(api.frameContext({contentDocument:doc,contentWindow:child},expected+'&different=1'),null);
Object.defineProperty(doc,'readyState',{value:'loading',configurable:true});
assert.equal(api.frameContext({contentDocument:doc,contentWindow:child},expected),null);
Object.defineProperty(doc,'readyState',{value:'complete',configurable:true});
const result=api.frameContext({contentDocument:doc,contentWindow:child},expected);
assert.equal(result.doc,doc);assert.equal(result.win,child);
console.log(JSON.stringify({finalTuple:true,rejected:4}));
""")
    assert result["rejected"] == 4


def test_all_shared_and_navigation_svg_variants_bind_cache_first_and_cancel_pending():
    result = _run(r"""
const selected=api.cases().filter(item=>item.renderer==='svg' && item.family!=='canonical-pretrip');
const initial=JSON.stringify(api.state);
for(const entry of selected) {
  api.calls.length=0;
  const ready=await api.prepare(entry,{projectId:api.projectId()});
  assert.ok(ready.adapter,entry.key+': '+ready.detail);
  assert.equal(ready.adapter.viewport.isConnected,true);
  assert.equal(ready.adapter.viewport.dataset.mapRudyUpdates,'false');
  assert.ok(api.calls.findIndex(item=>item[0]==='cache-only')<api.calls.findIndex(item=>item[0]==='bind-viewports'));
  const rendered=api.calls.find(item=>item[0].startsWith('render-'));
  if(entry.family==='architecture') assert.equal(rendered[1],entry.variant);
  if(entry.family==='navigation') {
    const [domain,mode,lens]=entry.variant.split(':');
    assert.equal(rendered[1],domain);assert.equal(rendered[2],lens);
    assert.equal(rendered[0],mode==='loading'?'render-loading':'render-fallback');
  }
  const layer=ready.viewport.querySelector('[data-dashboard-rudy-tile-layer]');
  const receipt=await ready.dispose();
  assert.equal(receipt.disposed,true);assert.equal(receipt.activeMaps,0);assert.equal(receipt.pendingInitializations,0);
  if(layer) {
    assert.equal(layer.querySelector('[data-dashboard-rudy-tile-generation="pending"]'),null);
    assert.equal(layer.dataset.dashboardRudyPendingTileKey,undefined);
    assert.ok(api.calls.some(item=>item[0]==='cancel-svg-generation'));
  } else {
    assert.ok(entry.domain==='terrain' || entry.domain==='prior');
    assert.ok(entry.variant.includes(':fallback:'));
  }
  assert.equal(await ready.dispose(),receipt,'Disposal must be idempotent');
  assert.equal(JSON.stringify(api.state),initial);assert.equal(window.document.getElementById('workspace').children.length,0);
}
console.log(JSON.stringify({cases:selected.length}));
""")
    assert result["cases"] == 22


@pytest.mark.parametrize("flag", ["diagnosticNativeTiles=1", "native=1", "refresh=1"])
def test_native_or_refresh_flags_are_rejected_before_loading(flag):
    result = _run("""
window.history.replaceState(null,'',window.location.href+'&'+%s);
await assert.rejects(api.prepare(api.cases()[0],{projectId:api.projectId()}),/cache-only/);
assert.equal(api.calls.length,0);console.log(JSON.stringify({blocked:true}));
""" % json.dumps(flag))
    assert result["blocked"]


def test_wrong_project_and_substituted_variant_are_rejected_before_loading():
    result = _run(r"""
const entry=api.cases()[0];
await assert.rejects(api.prepare(entry,{projectId:'other'}),/workspace/);
await assert.rejects(api.prepare({...entry,variant:'substituted'},{projectId:api.projectId()}),/substituted/);
assert.equal(api.calls.length,0);console.log(JSON.stringify({blocked:2}));
""")
    assert result["blocked"] == 2


def test_all_navigation_maplibre_lenses_use_visible_canvas_and_actual_lifecycle():
    result = _run(r"""
const selected=api.cases().filter(item=>item.family==='navigation' && item.renderer==='maplibre');
for(const entry of selected) {
  api.calls.length=0;
  const ready=await api.prepare(entry,{projectId:api.projectId()});
  assert.ok(ready.adapter,entry.key+': '+ready.detail);
  assert.equal(ready.adapter.viewport.tagName,'CANVAS');assert.equal(ready.adapter.viewport.isConnected,true);
  assert.equal(ready.adapter.camera().zoom,14);
  assert.equal(ready.adapter.control('pan'),null,'Missing production control must not be fabricated');
  assert.equal(ready.adapter.hintTargets().length,0,'Canvas evidence must not use hidden SVG');
  assert.equal(ready.adapter.policy().available,true);
  const render=api.calls.find(item=>item[0]==='render-navigation-maplibre');
  assert.equal(render.slice(1).join(':'),entry.variant);
  const original=api.runtime.maps[0],receipt=await ready.dispose();
  assert.equal(receipt.disposed,true);assert.equal(receipt.pendingInitializations,0);
  assert.equal(original.rudyTransport.destroyed,true);assert.equal(original.rudyTransport.controllers.size,0);
  assert.equal(api.runtime.maps.length,0);
}
console.log(JSON.stringify({cases:selected.length}));
""")
    assert result["cases"] == 14


@pytest.mark.parametrize("renderer", ["svg", "maplibre"])
def test_navigation_domain_mismatch_cannot_substitute_an_observed_renderer(renderer):
    result = _run("const renderer=" + json.dumps(renderer) + ";\n" + r"""
const entry=api.cases().find(item=>item.domain==='terrain' && item.renderer===renderer && !item.variant.includes(':loading:'));
await assert.rejects(api.prepare({...entry,domain:'observed'},{projectId:api.projectId()}),/substituted/);
assert.equal(api.calls.length,0);
api.options.actualDomain='observed';
const result=await api.prepare(entry,{projectId:api.projectId()});
assert.equal(result.adapter,undefined);assert.match(result.detail,/domain/);
assert.equal(result.cleanup.disposed,true);assert.equal(api.runtime.maps.length,0);
console.log(JSON.stringify({rejected:true,cleaned:true}));
""")
    assert result == {"rejected": True, "cleaned": True}


def test_navigation_native_template_is_rejected_before_map_initialization():
    result = _run(r"""
api.options.template='/admin/tiles/rudy.png?native=1&exact=1';
const entry=api.cases().find(item=>item.family==='navigation' && item.renderer==='maplibre');
const result=await api.prepare(entry,{projectId:api.projectId()});
assert.equal(result.adapter,undefined);assert.match(result.detail,/not cache-only/);
assert.ok(!api.calls.some(item=>item[0]==='init-navigation'));
assert.equal(result.cleanup.disposed,true);assert.equal(api.runtime.maps.length,0);
console.log(JSON.stringify({blocked:true}));
""")
    assert result["blocked"]


def test_main_weather_both_renderers_wait_for_final_frame_and_dispose_bridge():
    result = _run(r"""
const selected=api.cases().filter(item=>item.family==='canonical-pretrip');
for(const entry of selected) {
  api.calls.length=0;
  const ready=await api.prepare(entry,{projectId:api.projectId()});
  assert.ok(ready.adapter,entry.key+': '+ready.detail);
  assert.equal(ready.adapter.viewport.id,entry.renderer==='maplibre'?'mapLibreEvidenceMap':'map');
  assert.equal(Boolean(ready.adapter.viewport.closest('[hidden]')),false);
  const frame=window.document.querySelector('iframe'),url=new URL(frame.src);
  assert.equal(url.pathname,'/admin/pretrip');assert.equal(url.searchParams.get('projectId'),api.projectId());
  assert.equal(url.searchParams.get('diagnosticMapProbe'),'1');assert.equal(url.searchParams.get('wheelZoom'),'0');
  assert.equal(url.searchParams.get('diagnosticInteractionCase'),entry.key);
  for(const name of ['native','refresh','diagnosticNativeTiles']) assert.equal(url.searchParams.has(name),false);
  assert.ok(api.calls.some(item=>item[0]===(entry.id==='weather-map'?'bind-weather':'bind-main')));
  if(entry.renderer==='maplibre') assert.equal(ready.adapter.hintTargets().length,0,'Hidden SVG evidence is not a canvas hint target');
  else assert.equal(ready.adapter.hintTargets().length,1);
  const receipt=await ready.dispose();assert.equal(receipt.disposed,true);assert.equal(receipt.children.length,1);
  assert.equal(window.document.querySelector('iframe'),null);
}
console.log(JSON.stringify({cases:selected.length}));
""")
    assert result["cases"] == 4


@pytest.mark.parametrize("failure", ["missingCancel", "leakCanvas", "leakTransport"])
def test_incomplete_cleanup_stays_an_explicit_failed_receipt(failure):
    result = _run("""
api.options[%s]=true;
const entry=api.cases().find(item=>%s);
const ready=await api.prepare(entry,{projectId:api.projectId()});assert.ok(ready.adapter,ready.detail);
const receipt=await ready.dispose();assert.equal(receipt.disposed,false);assert.ok(receipt.errors.length>0);
assert.equal(receipt.pendingInitializations,null);console.log(JSON.stringify({detected:true}));
""" % (json.dumps(failure), "item.id==='overview-map'" if failure == "missingCancel" else "item.family==='navigation' && item.renderer==='maplibre'"))
    assert result["detected"]


def test_canonical_renderer_fallback_is_a_gap_and_incomplete_child_cleanup_is_preserved():
    result = _run(r"""
api.options.actualRenderer='svg';api.options.childReceipt={disposed:false,activeMaps:1,pendingInitializations:1,errors:['fixture leak']};
const entry=api.cases().find(item=>item.id==='map' && item.renderer==='maplibre');
const result=await api.prepare(entry,{projectId:api.projectId()});
assert.equal(result.adapter,undefined);assert.match(result.detail,/Requested maplibre; actual renderer is svg/);
assert.equal(result.cleanup.disposed,false);assert.equal(result.cleanup.children[0].activeMaps,1);
assert.equal(window.document.querySelector('iframe'),null);
console.log(JSON.stringify({fallbackReported:true,cleanupReported:true}));
""")
    assert result == {"fallbackReported": True, "cleanupReported": True}
