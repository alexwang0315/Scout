"""Exercise the additional-map Diagnostic through production DOM handlers.

The DOM has no network or browser layout. CSS metrics and a generated tile URL
are fixture inputs; this does not certify native tiles or trusted mouse capture.
"""

import hashlib
import json
import re
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "docs/admin/scout-dashboard-v0.1.html"


@pytest.fixture(scope="module", autouse=True)
def _source_receipt(record_testsuite_property):
    record_testsuite_property("dashboard_source_sha256", hashlib.sha256(PAGE.read_bytes()).hexdigest())
    debug = ROOT / "docs/admin/phase-3-5-runtime-debug.html"
    record_testsuite_property("debug_source_sha256", hashlib.sha256(debug.read_bytes()).hexdigest())
    vendor = ROOT / "docs/admin/vendor/maplibre-gl/6.2.0/maplibre-gl.mjs"
    record_testsuite_property("maplibre_vendor_sha256", hashlib.sha256(vendor.read_bytes()).hexdigest())


def _run(body):
    setup = r"""
const assert = require('node:assert/strict'), fs = require('node:fs'), {JSDOM} = require('jsdom');
const html = fs.readFileSync('docs/admin/scout-dashboard-v0.1.html', 'utf8');
const dom = new JSDOM('<body><button id="sentinel">untouched</button></body>', {
  url:'http://localhost/admin/dashboard?projectId=dongqing_batongguan_historic_trail_newImport&diagnosticMapProbe=1',
  runScripts:'outside-only',
});
const {window} = dom;
window.structuredClone = structuredClone;
window.matchMedia = () => ({matches:false});
window.fetch = () => {throw Error('Unexpected network access')};
window.__vendorKeyboard = () => {
  const vendor=fs.readFileSync('docs/admin/vendor/maplibre-gl/6.2.0/maplibre-gl.mjs','utf8');
  const marker=vendor.indexOf('switch(e.keyCode)');assert.ok(marker>0,'Vendored keyboard handler changed');
  const declaration=vendor.slice(vendor.lastIndexOf('var ',marker),vendor.indexOf(';function',marker));
  const implementation=declaration.slice(declaration.indexOf('class'));
  const Keyboard=new Function('Rf','Bf','Un','return ('+implementation+')')(
    {panStep:100,bearingStep:15,pitchStep:10},value=>value,value=>value);
  return new Keyboard(null,{zoom:14,bearing:0,pitch:0,center:[121,23.5]});
};
window.vendorKeyboardEvents=[];
window.Element.prototype.getBoundingClientRect = function() {
  const viewport = this.matches('[data-dashboard-map-viewport]');
  return {left:0, top:0, right:viewport?760:24, bottom:viewport?248:24, width:viewport?760:24, height:viewport?248:24};
};
const source = [...html.matchAll(/<script(?: [^>]*)?>([\s\S]*?)<\/script>/g)]
  .map(match=>match[1]).find(script=>script.includes('const DIAGNOSTIC_MAP_PROBE'));
window.eval(source + `
window.exercise = async (failure = '') => {
  const previous = {...state};
  const host = document.createElement('div');
  const hint = document.createElement('div');
  hint.id = 'dashboardMapHoverHint'; hint.hidden = true; hint.innerHTML = '<strong></strong><span></span>';
  const originalUpdate = updateDashboardRudyTileLayer;
  // Tile transport has separate executable tests; these checks operate controls.
  updateDashboardRudyTileLayer = viewport => {
    if (viewport.dataset.mapRudyUpdates !== 'false') throw Error('Interaction probe enabled native tiles');
  };
  const cp = (anchor_id, route_order_m, lat, lon) => ({anchor_id, route_order_m, lat, lon, display_label:anchor_id});
  const anchors = [cp('cp0',0,23.46,121.04),cp('cp1',1000,23.464,121.047),cp('cp2',2000,23.478,121.063)];
  const days = anchors.slice(0,2).map((anchor,i)=>({mission_day_id:'D'+(i+1),day_kind:'on_trail',start_anchor:anchor,
    primary_day_end_proposal:{target:anchors[i+1]}}));
  document.body.append(host, hint);
  try {
    state.permissionBaselineMapContext = {project_id:projectId(), route_points:anchors, anchors};
    state.permissionBaselineDraft = {candidate_only:true, accepted:false, days};
    state.mapViewportById = {};
    state.permissionDayMapGeometryById = {};
    host.innerHTML = days.map(renderPermissionDayMap).join('');
    for (const viewport of host.querySelectorAll('[data-dashboard-map-viewport]')) {
      const stage = viewport.querySelector('[data-dashboard-map-stage]');
      for (const [node, properties] of [[viewport,{clientWidth:760,clientHeight:248}],
        [stage,{offsetWidth:760,scrollWidth:760,offsetHeight:248,scrollHeight:248}]]) {
        for (const [name,value] of Object.entries(properties)) Object.defineProperty(node,name,{value,configurable:true});
      }
    }
    bindPermissionDayMaps(); diagnosticSetMapInteractionCacheOnly(host); bindDashboardMapHints(); bindDashboardMapViewports();
    const reports = [];
    for (const [index,viewport] of [...host.querySelectorAll('[data-dashboard-map-viewport]')].entries()) {
      const geometry = permissionDayMapGeometry(days[index]);
      viewport.querySelector('[data-dashboard-rudy-tile-layer]').innerHTML = navigationRudyTileImages(
        geometry.bounds, geometry.bounds, navigationRudyBaseZoom(geometry.bounds),760,248,permissionDayMapViewportId(days[index]),{cacheOnly:true});
      for (const image of viewport.querySelectorAll('image')) {
        const url = new URL(image.getAttribute('href'),location.href);
        if (url.searchParams.has('native') || url.searchParams.get('cache_only') !== '1') throw Error('Interaction tile fixture escaped cache-only');
      }
      if (failure === 'broken-plus') viewport.querySelector('[data-dashboard-map-controls]').addEventListener('click',event=> {
        if (event.target.closest('[data-map-control="zoom-in"]')) event.stopImmediatePropagation();
      },true);
      if (failure === 'wheel-consumed') viewport.addEventListener('wheel',event=>event.preventDefault());
      if (failure.startsWith('missing-box')) {
        viewport.querySelector('[data-map-control="box-zoom"]').remove();
        viewport.addEventListener('keydown',event=>{if(event.key==='b')event.stopImmediatePropagation()},true);
        if(failure==='missing-box-and-wheel')viewport.addEventListener('wheel',event=>event.preventDefault());
      }
      if (failure === 'vendor-keyboard') {
        const handler=window.__vendorKeyboard();
        viewport.addEventListener('keydown',event=>{
          if(!event.key.startsWith('Arrow') || event.target!==viewport)return;
          const result=handler.keydown(event);
          let offset=null;
          result?.cameraAnimation?.({easeTo:options=>{offset=options.offset},getZoomSnap:()=>0});
          window.vendorKeyboardEvents.push({key:event.key,keyCode:event.keyCode,code:event.code,offset});
        });
      }
      if (failure === 'missing-hint') viewport.querySelectorAll('[data-dashboard-map-hint-title]').forEach(node=>node.removeAttribute('data-dashboard-map-hint-title'));
      if (failure === 'hidden-hint') viewport.querySelectorAll('[data-dashboard-map-hint-title]').forEach(node=>node.style.visibility='hidden');
      if (failure === 'not-focusable') viewport.querySelectorAll('[data-dashboard-map-hint-title]').forEach(node=>node.removeAttribute('tabindex'));
      if (failure === 'wrong-workspace') viewport.querySelector('image').setAttribute('href', '/admin/tiles/imagery/other/rudy-twmap/12/1/1.png?source_id=happyman_rudy_twmap&exact=1');
      if (failure === 'native-url') {
        const image=viewport.querySelector('image'), url=new URL(image.getAttribute('href'),location.href);
        url.searchParams.delete('cache_only');url.searchParams.set('native','1');image.setAttribute('href',url.href);
      }
      if (failure === 'missing-tiles') viewport.querySelectorAll('image').forEach(node=>node.remove());
      const adapter = diagnosticSharedMapInteractionAdapter(viewport);
      // Let the production drag handler's ghost-click suppression expire
      // before the next independent control action, as separate UI events do.
      adapter.settle = () => new Promise(resolve=>window.setTimeout(resolve,0));
      reports.push(...await diagnosticExerciseMapInteractionDom({id:viewport.dataset.dashboardMapViewport,renderer:'svg'},adapter));
    }
    return reports;
  } finally {
    host.remove(); hint.remove();
    updateDashboardRudyTileLayer = originalUpdate;
    for (const key of Object.keys(state)) if (!(key in previous)) delete state[key];
    Object.assign(state,previous);
  }
};
window.aggregate = async (rows, expected = [], cleanup = {disposed:true,activeMaps:0,pendingInitializations:0,errors:[]}) => {
  const original = diagnosticAdditionalMapInteractions;
  try {
    diagnosticAdditionalMapInteractions = async () => ({rows, expected, cleanup});
    return await diagnosticMapInteractionCoverage('DASH-029','9 legacy source contracts');
  } finally { diagnosticAdditionalMapInteractions = original; }
};
window.snapshot = () => JSON.stringify(state);
window.interactionCases = () => diagnosticMapInteractionSurfaceCases();
window.completeRows = (rows, dispose) => diagnosticCompleteMapInteractionRows(rows, dispose);
window.inspectPolicy = (inventory, layers) => diagnosticMapLibreInteractionPolicy({
  getRenderPolicySources:()=>inventory,inspectLayerOrder:()=>({layers})
});
window.verifyPolicy = (surface, policy) => diagnosticMapInteractionRenderPolicy(surface, {
  doc:document,rudyCacheLayer:'imagery',policy:()=>policy
});
window.lifecycleDisposals = 0;
window.lifecycle = async (shouldFail, receipt = {disposed:true,activeMaps:0,pendingInitializations:0,errors:[]}) => {
  const resolver = diagnosticRudyPermissionContext, waiter = diagnosticWaitForMapOrder;
  diagnosticResourceCache.clear();
  const expectedProject = projectId();
  try {
    diagnosticRudyPermissionContext = async selected => {
      if (selected !== expectedProject) throw Error('Wrong selected project');
      return {dailyIds:['D1'],permissionBaselineDraft:{days:[]},dailyEvidence:{source:'fixture'}};
    };
    diagnosticWaitForMapOrder = async read => {
      const frame = document.querySelector('[data-diagnostic-map-interaction-probe]');
      if (!frame?.isConnected || new URL(frame.src).searchParams.get('projectId') !== expectedProject)
        throw Error('Isolation iframe not scoped to workspace');
      if (new URL(frame.src).searchParams.has('diagnosticNativeTiles')) throw Error('Unexpected native access');
      frame.contentWindow.scoutDashboardDiagnostics={dispose:async()=>{
        if(!frame.isConnected)throw Error('Frame removed before disposing active renderer');
        window.lifecycleDisposals++;return receipt;
      }};
      return {run:async context => {
        if (shouldFail) throw Error('Fixture frame failure');
        return [];
      }};
    };
    return await diagnosticAdditionalMapInteractions();
  } finally { diagnosticRudyPermissionContext=resolver; diagnosticWaitForMapOrder=waiter; }
};
`);
"""
    script = setup + "\n(async()=>{\n" + body + r"""
})().catch(error=>{console.error(error);process.exitCode=1}).finally(()=>window.close());
"""
    result = subprocess.run(["node", "-e", script], cwd=ROOT, text=True, capture_output=True, timeout=90)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_each_daily_dom_exercises_hints_controls_keyboard_box_drag_and_policy():
    result = _run(r"""
const before = window.snapshot();
const rows = await window.exercise();
assert.equal(window.snapshot(),before,'Diagnostic changed live state');
assert.equal(window.document.body.textContent,'untouched','Diagnostic leaked DOM');
assert.equal(rows.length,8);
assert.equal(new Set(rows.map(row=>row.id)).size,2);
for (const row of rows) assert.equal(row.status,'passed',row.check+': '+row.detail);
for (const row of rows.filter(row=>row.check==='DASH-027')) {
  assert.equal(row.evidence.keys.length,4);
  assert.equal(row.evidence.reverseRectangleZoomIn,true);
  assert.equal(row.evidence.wheelDefaultNotPrevented,true);
  assert.equal(row.evidence.reverse_rectangle_policy,'any_direction_zoom_in_minus_zoom_out');
  assert.equal(row.evidence.minusZoomOut,true);
  assert.ok(row.evidence.subchecks.every(check=>check.status==='passed'));
}
for (const row of rows) {
  assert.equal(row.trustedPointerCaptureVerified,false);
  assert.equal(row.nativeTileCompletenessVerified,false);
  assert.equal(row.realPageScrollVerified,false);
}
console.log(JSON.stringify(rows));
""")
    assert len(result) == 8


def test_synthetic_arrows_reach_the_actual_vendored_maplibre_keyboard_handler():
    result = _run(r"""
await window.exercise('vendor-keyboard');
assert.equal(window.vendorKeyboardEvents.length,8);
for(const event of window.vendorKeyboardEvents) {
  assert.ok(event.keyCode>=37 && event.keyCode<=40);
  assert.equal(event.code,event.key);
  assert.ok(event.offset && event.offset.some(value=>value!==0),'Actual MapLibre handler ignored synthetic '+event.key);
}
assert.equal(new Set(window.vendorKeyboardEvents.map(event=>event.key)).size,4);
console.log(JSON.stringify({arrows:window.vendorKeyboardEvents.length,vendorCameraAnimations:8}));
""")
    assert result == {"arrows": 8, "vendorCameraAnimations": 8}


@pytest.mark.parametrize(
    ("failure", "case_id", "status", "reason"),
    [
        ("broken-plus", "DASH-029", "failed", "plus did not zoom"),
        ("wheel-consumed", "DASH-027", "failed", "consumed page scrolling"),
        ("missing-hint", "DASH-026", "warning", "no inspectable evidence"),
        ("hidden-hint", "DASH-026", "warning", "no inspectable evidence"),
        ("not-focusable", "DASH-026", "failed", "not keyboard focusable"),
        ("wrong-workspace", "DASH-028", "failed", "workspace or exact policy differs"),
        ("native-url", "DASH-028", "failed", "escaped its cache-only boundary"),
        ("missing-tiles", "DASH-028", "warning", "no actual Rudy tile URL"),
        ("missing-box", "DASH-027", "failed", "box-zoom control missing"),
    ],
)
def test_negative_dom_evidence_is_preserved_and_state_restored(failure, case_id, status, reason):
    result = _run(f"""
const before = window.snapshot();
const rows = await window.exercise({json.dumps(failure)});
assert.equal(window.snapshot(),before);
assert.equal(window.document.body.textContent,'untouched');
console.log(JSON.stringify(rows));
""")
    selected = [row for row in result if row["check"] == case_id]
    assert len(selected) == 2
    assert all(row["status"] == status and reason in row["detail"] for row in selected)


def test_coverage_aggregation_cannot_turn_failed_missing_or_empty_rows_into_pass():
    result = _run(r"""
const run = rows => window.aggregate(rows.map(row=>({...row,check:'DASH-029'})));
const failed = await run([{status:'passed',id:'D1'},{status:'failed',id:'debug-map',detail:'broken handler'}]);
const missing = await run([{status:'warning',id:'permission-day-maps',detail:'no candidate'}]);
const empty = await run([]);
assert.equal(failed.status,'failed');
assert.equal(missing.status,'warning');
assert.equal(empty.status,'warning');
assert.equal(failed.mapInteractions.rows[1].detail,'broken handler');
console.log(JSON.stringify({failed:failed.status,missing:missing.status,empty:empty.status}));
""")
    assert result == {"failed": "failed", "missing": "warning", "empty": "warning"}


def test_coverage_requires_every_renderer_lens_and_daily_instance_exactly_once():
    result = _run(r"""
const expected=[...window.interactionCases(),{id:'debug-map',renderer:'svg'},{id:'debug-map',renderer:'maplibre'},{id:'D1',renderer:'svg'}];
const rows=expected.map(surface=>({...surface,check:'DASH-029',status:'passed'}));
const complete=await window.aggregate(rows,expected);
const missing=await window.aggregate(rows.slice(0,-1),expected);
const duplicate=await window.aggregate([...rows,rows[0]],expected);
const navigation=expected.find(surface=>surface.id==='navigation-map'&&surface.variant==='observed:3d:risk');
const missingLens=await window.aggregate(rows.filter(row=>row.key!==navigation.key),expected);
const unexpected=await window.aggregate([...rows,{id:'unlisted-map',renderer:'svg',check:'DASH-029',status:'passed'}],expected);
assert.equal(complete.status,'passed');
assert.equal(missing.status,'warning');assert.equal(missing.mapInteractions.missing[0].id,'D1');
assert.equal(duplicate.status,'warning');
assert.equal(missingLens.status,'warning');assert.equal(missingLens.mapInteractions.missing[0].key,navigation.key);
assert.equal(unexpected.status,'warning');assert.equal(unexpected.mapInteractions.unexpected[0].id,'unlisted-map');
console.log(JSON.stringify({complete:complete.status,missing:missing.status,duplicate:duplicate.status,missingLens:missingLens.status,unexpected:unexpected.status}));
""")
    assert result == {"complete": "passed", "missing": "warning", "duplicate": "warning", "missingLens": "warning", "unexpected": "warning"}


def test_each_new_domain_loading_and_time_window_case_remains_required():
    result = _run(r"""
const expected=window.interactionCases(),rows=expected.map(surface=>({...surface,check:'DASH-029',status:'passed'}));
const additions=expected.filter(surface=>['terrain','prior'].includes(surface.domain)
  || surface.id==='architecture-map' && surface.variant==='time_window');
assert.equal(additions.length,9);
for(const absent of additions) {
  const result=await window.aggregate(rows.filter(row=>row.key!==absent.key),expected);
  assert.equal(result.status,'warning',absent.key);
  assert.equal(result.mapInteractions.missing.length,1);
  assert.equal(result.mapInteractions.missing[0].key,absent.key);
}
const terrain=additions.find(surface=>surface.variant==='terrain:2d:structure');
for(const forged of [{...terrain,domain:'observed'}, {...terrain,variant:'observed:2d:structure'}]) {
  const substituted=rows.map(row=>row.key===terrain.key?{...forged,check:'DASH-029',status:'passed'}:row);
  const result=await window.aggregate(substituted,expected);
  assert.equal(result.status,'warning');assert.ok(result.mapInteractions.missing.some(row=>row.key===terrain.key));
  assert.equal(result.mapInteractions.unexpected.length,1,'Copied key cannot hide a different actual domain');
}
console.log(JSON.stringify({required:additions.length,forgeriesRejected:2}));
""")
    assert result == {"required": 9, "forgeriesRejected": 2}


@pytest.mark.parametrize("failure", ["missing-box", "missing-box-and-wheel"])
def test_missing_box_fails_without_omitting_wheel_and_outside_focus_observations(failure):
    result = _run("const failure=" + json.dumps(failure) + ";\n" + r"""
const rows=(await window.exercise(failure)).filter(row=>row.check==='DASH-027');
for(const row of rows) {
  assert.equal(row.status,'failed');
  const find=name=>row.evidence.subchecks.find(item=>item.name===name);
  assert.equal(find('box_keyboard_activation').status,'failed');
  assert.equal(find('forward_rectangle').status,'failed');
  assert.equal(find('wheel_page_scroll').status,failure==='missing-box'?'passed':'failed');
  assert.equal(find('editable_key_preserved').status,'passed');
  assert.equal(find('outside_focus_key_preserved').status,'passed');
  assert.equal(row.evidence.reverse_rectangle_policy,'any_direction_zoom_in_minus_zoom_out');
}
console.log(JSON.stringify({cases:rows.length,failuresPreserved:true}));
""")
    assert result == {"cases": 2, "failuresPreserved": True}


def test_navigation_ready_domain_requires_vectors_while_loading_requires_truthful_state():
    result = _run(r"""
const cases=window.interactionCases();
const policy={vectorCount:2,unapprovedImageCount:0,rudySourceCount:0,rasterTileSourceCount:0,tileUrls:[],evidenceDomain:'terrain',basemapLayer:'none'};
const ready=cases.filter(surface=>['terrain','prior'].includes(surface.domain) && !surface.variant.includes(':loading:'));
assert.equal(ready.length,6);
for(const entry of ready) {
  const actual={...policy,evidenceDomain:entry.domain,navigationState:{renderer:entry.renderer,state:'ready',noVectorsClaim:false}};
  assert.equal(window.verifyPolicy(entry,actual).inspectedRudySources,0);
  assert.throws(()=>window.verifyPolicy(entry,{...actual,evidenceDomain:'observed'}),/domain or basemap/);
  assert.throws(()=>window.verifyPolicy(entry,{...actual,basemapLayer:'rudy-twmap'}),/domain or basemap/);
  assert.throws(()=>window.verifyPolicy(entry,{...actual,rudySourceCount:1}),/unexpectedly includes a Rudy source/);
  assert.throws(()=>window.verifyPolicy(entry,{...actual,rasterTileSourceCount:1}),/unexpectedly includes a Rudy source/,'Unlabelled raster cannot disguise Rudy');
  assert.throws(()=>window.verifyPolicy(entry,{...actual,rudySourceCount:undefined}),/absence cannot be verified/);
  assert.throws(()=>window.verifyPolicy(entry,{...actual,vectorCount:0}),/vector evidence is absent/);
  assert.throws(()=>window.verifyPolicy(entry,{...actual,navigationState:{...actual.navigationState,state:'loading'}}),/not ready/);
}
const url='http://localhost/admin/tiles/imagery/dongqing_batongguan_historic_trail_newImport/imagery/12/1/1.png?source_id=happyman_rudy_twmap&exact=1&cache_only=1';
for(const entry of cases.filter(surface=>surface.family==='navigation'&&surface.variant.includes(':loading:'))) {
  const loading={...policy,evidenceDomain:undefined,basemapLayer:'rudy-twmap',rudySourceCount:1,tileUrls:[url],vectorCount:0,
    navigationState:{renderer:'svg',state:'loading',workspaceState:'loading',statusVisible:true,claimVisible:true,noVectorsClaim:true,
      title:'Loading workspace terrain evidence.',svgLabel:'Navigation orientation map; terrain evidence loading'}};
  const checked=window.verifyPolicy(entry,loading);
  assert.equal(checked.mapState,'loading');assert.equal(checked.readyVectorEvidenceVerified,false);
  assert.throws(()=>window.verifyPolicy(entry,{...loading,navigationState:undefined}),/does not truthfully expose/);
  assert.throws(()=>window.verifyPolicy(entry,{...loading,navigationState:{...loading.navigationState,state:'ready'}}),/does not truthfully expose/);
  assert.throws(()=>window.verifyPolicy(entry,{...loading,tileUrls:[]}),/no actual Rudy tile URL/);
  assert.equal(checked.inspectedRudyTileUrls,1);
  assert.throws(()=>window.verifyPolicy(entry,{...loading,tileUrls:[url.replace('cache_only=1','native=1')]}),/cache-only boundary/);
}
console.log(JSON.stringify({readyCases:ready.length,loadingDomains:3}));
""")
    assert result == {"readyCases": 6, "loadingDomains": 3}


def test_daily_d028_retains_visible_vectors_and_cache_only_tile_requirement():
    result = _run(r"""
const present=(await window.exercise()).filter(row=>row.check==='DASH-028');
assert.equal(present.length,2);
for(const row of present){assert.equal(row.status,'passed',row.detail);assert.ok(row.evidence.vectorCount>0);assert.equal(row.evidence.readyVectorEvidenceVerified,true)}
const absent=(await window.exercise('missing-tiles')).filter(row=>row.check==='DASH-028');
for(const row of absent){assert.equal(row.status,'warning');assert.equal(row.evidence.readyVectorEvidenceVerified,false)}
console.log(JSON.stringify({ready:present.length,missingTiles:absent.length}));
""")
    assert result == {"ready": 2, "missingTiles": 2}


def test_unverified_or_failed_cleanup_never_becomes_pass_and_preserves_failed_evidence():
    result = _run(r"""
const rows=[{id:'fixture',status:'passed',detail:'controls worked'},
  {id:'fixture',status:'failed',detail:'broken handler'},
  {id:'fixture',status:'warning',detail:'missing real geometry'}];
const receipt={disposed:true,activeMaps:0,pendingInitializations:0,errors:[]};
const clean=await window.completeRows(rows,async()=>receipt);
assert.deepEqual(clean.map(row=>row.status),['passed','failed','warning']);
assert.ok(clean.every(row=>row.cleanupVerified));
const results=[];
for(const invalid of [null,{...receipt,activeMaps:1},{...receipt,pendingInitializations:1},
  {...receipt,disposed:false},{...receipt,errors:['transport still active']},{...receipt,errors:null}]) {
  const incomplete=await window.completeRows(rows,async()=>invalid);
  assert.deepEqual(incomplete.map(row=>row.status),['warning','failed','warning']);
  assert.ok(incomplete.every(row=>!row.cleanupVerified));
  assert.match(incomplete[1].detail,/broken handler/);
  results.push(incomplete[0].status);
}
const rejected=await window.completeRows(rows,async()=>{throw Error('cleanup failed')});
assert.equal(rejected[0].status,'warning');assert.equal(rejected[1].status,'failed');
assert.deepEqual(Array.from(rejected[0].cleanup.errors),['cleanup failed']);
console.log(JSON.stringify({clean:clean[0].status,incomplete:results,rejected:rejected[0].status}));
""")
    assert result["clean"] == "passed"
    assert result["incomplete"] == ["warning"] * 6
    assert result["rejected"] == "warning"


def test_outer_frame_cleanup_gap_cannot_be_hidden_by_complete_case_rows():
    result = _run(r"""
const expected=window.interactionCases(),rows=expected.map(surface=>({...surface,check:'DASH-029',status:'passed'}));
for(const cleanup of [undefined,null,{disposed:false,activeMaps:1,pendingInitializations:0,errors:[]},
  {disposed:true,activeMaps:0,pendingInitializations:1,errors:[]},{disposed:true,activeMaps:0,pendingInitializations:0,errors:['active renderer']}]) {
  const result=await window.aggregate(rows,expected,cleanup===undefined?{}:cleanup);
  assert.equal(result.status,'warning');assert.equal(result.mapInteractions.outerCleanupVerified,false);
  assert.equal(result.mapInteractions.rows.length,40);assert.ok(result.mapInteractions.rows.every(row=>row.status==='passed'));
  const failed=await window.aggregate([{...rows[0],status:'failed'},...rows.slice(1)],expected,cleanup===undefined?{}:cleanup);
  assert.equal(failed.status,'failed');
}
console.log(JSON.stringify({outerGapsPreserved:5}));
""")
    assert result == {"outerGapsPreserved": 5}


def test_maplibre_policy_requires_actual_style_inventory_and_transport_mapping():
    result = _run(r"""
const layers=[{visible:true,hasContent:true,role:'route'},{visible:false,hasContent:true,role:'checkpoint'}];
const rudy={type:'raster',tiles:['scout-raster-2://1/rudy-twmap/0/{z}/{x}/{y}'],
  requestTemplates:['http://localhost/admin/tiles/imagery/fixture/rudy-twmap/{z}/{x}/{y}.png?source_id=happyman_rudy_twmap&exact=1&cache_only=1'],
  layers:[{metadata:{'scout:layer_id':'rudy-twmap'}}]};
const image={type:'image',url:'/hillshade.png',coordinates:[[121,24],[122,24],[122,23],[121,23]],
  layers:[{metadata:{'scout:layer_id':'terrain-hillshade','scout:source_type':'image','scout:candidate_only':true,'scout:runtime_safety_truth':false}}]};
const cwa={...image,url:'/admin/pretrip/projects/dongqing_batongguan_historic_trail_newImport/weather-imagery/radar.png',
  layers:[{metadata:{'scout:layer_id':'cwa-weather-radar','scout:source_type':'image','scout:candidate_only':true,'scout:runtime_safety_truth':false}}]};
const run=sources=>window.inspectPolicy({activeRenderer:'maplibre',available:true,sources},layers);
const valid=run([rudy,image]);
assert.equal(valid.vectorCount,1);assert.equal(valid.unapprovedImageCount,0);assert.equal(valid.tileUrls.length,1);
assert.equal(valid.rasterTileSourceCount,1);assert.equal(valid.rudySourceCount,1);
const unlabelled=run([{...rudy,layers:[]}]);
assert.equal(unlabelled.rudySourceCount,0);assert.equal(unlabelled.rasterTileSourceCount,1);
assert.equal(valid.unmappedRudySourceCount,0);
assert.equal(run([rudy,cwa]).unapprovedImageCount,0,'Actual CWA image contract rejected');
assert.equal(run([rudy,{...cwa,url:'/admin/pretrip/projects/other/weather-imagery/radar.png'}]).unapprovedImageCount,1);
assert.equal(run([rudy,{...cwa,url:'https://example.invalid/admin/pretrip/projects/dongqing_batongguan_historic_trail_newImport/weather-imagery/radar.png'}]).unapprovedImageCount,1);
const unmapped=run([{...rudy,requestTemplates:null},image]);
assert.equal(unmapped.tileUrls.length,0);assert.equal(unmapped.unmappedRudySourceCount,1);
const mixed=run([rudy,{...rudy,requestTemplates:null}]);assert.equal(mixed.unmappedRudySourceCount,1);
const unapproved=run([rudy,{...image,layers:[{metadata:{'scout:layer_id':'arbitrary-image'}}]}]);
assert.equal(unapproved.unapprovedImageCount,1);
const unlocated=run([rudy,{...image,coordinates:null}]);assert.equal(unlocated.unapprovedImageCount,1);
const absent=window.inspectPolicy(null,layers);assert.equal(absent.unapprovedImageCount,null);
console.log(JSON.stringify({valid,unmapped,unapproved,unlocated,absent}));
""")
    assert result["valid"]["vectorCount"] == 1
    assert result["unmapped"]["unmappedRudySourceCount"] == 1


@pytest.mark.parametrize("fail", [False, True])
def test_isolation_iframe_is_removed_and_original_focus_restored_even_on_error(fail):
    result = _run(f"const shouldFail={json.dumps(fail)};\n" + r"""
const sentinel=window.document.getElementById('sentinel');sentinel.focus();
const before=window.snapshot();let caught=false;
try {
  const report=await window.lifecycle(shouldFail);
  assert.equal(report.cleanup.disposed,true);assert.equal(report.cleanupStatus,'passed');
}catch(error){caught=true;assert.match(error.message,/Fixture frame failure/);assert.equal(error.cleanupReceipt.disposed,true);}
assert.equal(caught,shouldFail);
assert.equal(window.lifecycleDisposals,1,'Outer renderer must dispose before its frame is removed');
assert.equal(window.document.querySelectorAll('[data-diagnostic-map-interaction-probe]').length,0);
assert.equal(window.document.activeElement,sentinel);
assert.equal(window.document.body.textContent,'untouched');
assert.equal(window.snapshot(),before);
console.log(JSON.stringify({caught,cleaned:true}));
""")
    assert result == {"caught": fail, "cleaned": True}


def test_outer_frame_failed_child_cleanup_is_reported_and_focus_is_still_restored():
    result = _run(r"""
const sentinel=window.document.getElementById('sentinel');sentinel.focus();
const report=await window.lifecycle(false,{disposed:false,activeMaps:1,pendingInitializations:1,errors:['retained canvas']});
assert.equal(report.cleanupStatus,'warning');assert.equal(report.cleanup.disposed,false);
assert.equal(report.cleanup.children[0].activeMaps,1);
assert.equal(window.lifecycleDisposals,1);assert.equal(window.document.activeElement,sentinel);
assert.equal(window.document.querySelectorAll('[data-diagnostic-map-interaction-probe]').length,0);
console.log(JSON.stringify({incomplete:true,removed:true,focusRestored:true}));
""")
    assert result == {"incomplete": True, "removed": True, "focusRestored": True}


def test_all_four_existing_checks_include_additional_dom_verification():
    source = PAGE.read_text()
    for number in (26, 27, 28, 29):
        body = re.search(rf"(?ms)^    async function diagnosticCheck0{number}\(.*?^    \}}", source).group()
        assert "diagnosticMapSurfaceSources()" in body
        assert f'diagnosticMapInteractionCoverage("DASH-0{number}"' in body


@pytest.mark.parametrize("broken", ["", "zoom", "wheel", "image", "reverse-shrinks", "minus-noop"])
def test_debug_adapter_runs_actual_bound_svg_camera_and_hint_handlers(broken):
    debug = (ROOT / "docs/admin/phase-3-5-runtime-debug.html").read_text()
    dashboard = PAGE.read_text()

    def extract(source, names):
        return "\n".join(re.search(rf"(?ms)^    (?:async )?function {name}\(.*?^    \}}", source).group() for name in names)

    source = r"""
const assert=require('node:assert/strict'),{JSDOM}=require('jsdom');
const dom=new JSDOM('<body><div><svg id="runtimeMap"></svg><div id="runtimeMapLibre"></div></div></body>',
  {url:'http://localhost/admin/debug?projectId=fixture&wheelZoom=0&diagnosticMapProbe=1'});
const window=dom.window, document=window.document;
const runtimeMap=document.getElementById('runtimeMap'),runtimeMapLibre=document.getElementById('runtimeMapLibre');
for(const id of ['debugClearButton','mobileIngressResetButton','zoomIn','zoomOut','fitRoute','refreshMapTiles','panMode','boxZoomMode','panUp','panDown','panLeft','panRight']) {
  const button=document.createElement('button');button.id=id;document.body.appendChild(button);
}
window.Element.prototype.getBoundingClientRect=function(){return {left:0,top:0,width:1000,height:720,right:1000,bottom:720}};
const debugPageState={zoom:1,panX:0,panY:0,mapInteractionMode:'pan',mapKeyboardActive:false,zoomSelection:null,panSelection:null};
const MAP_WIDTH=1000,MAP_HEIGHT=720,MAP_MIN_ZOOM=.6,MAP_MAX_ZOOM=12000,MAP_ZOOM_STEP_FACTOR=1.25,MAP_WHEEL_ZOOM_ENABLED=false;
const DASHBOARD_MAP_APPROVED_SINGLE_IMAGE_THEMES=['satellite','radar','lidar','hillshade','elevation_tint','slope_shading','contours','thematic'];
const normalizeDashboardSingleImageTheme=value=>String(value||'').toLowerCase().replace(/[^a-z0-9_-]+/g,'_');
const clamp=(value,low,high)=>Math.max(low,Math.min(high,value)),projectId=()=>'fixture';
const debugMapLibreActive=()=>false,debugMapInteractionMaxZoom=()=>12000;
const bindLayerMenuDismiss=()=>{},clearDebugProjection=()=>{},resetMobileWearableIngressProjection=()=>{};
const updateLayers=()=>{},applyLayerPreset=()=>{},toggleDebugRudyRefresh=()=>{},syncDebugRudyRefreshButton=()=>{};
const syncRasterBasemapLayers=()=>{},syncMapMarkerScale=()=>{},updatePointLabels=()=>{},updateMapZoomIndicator=()=>{},updateScaleBar=()=>{};
const highlightMapForEvent=()=>{},selectedMapEvent=()=>null,selectTimelineForMapTarget=()=>{};
const mapFeatureTitle=item=>item.display_label,mapFeatureSummary=item=>item.evidence_type;
const svgEl=(tag,attrs)=>{const node=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const [key,value] of Object.entries(attrs))node.setAttribute(key,value);return node;};
runtimeMap.getScreenCTM=()=>({inverse:()=>({})});
runtimeMap.createSVGPoint=()=>({x:0,y:0,matrixTransform(){
  const box=mapViewportBox();return {x:box.minX+this.x*box.width/1000,y:box.minY+this.y*box.height/720};
}});
""" + extract(debug, (
        "text", "mapFeatureKind", "mapFeatureAriaLabel", "attachMapEvidence",
        "mapHoverTooltip", "positionMapHoverTooltip", "showMapHoverTooltip", "hideMapHoverTooltip",
        "handleMapHoverPointerMove", "handleMapEvidenceFocus", "handleMapEvidenceKeyboard",
        "mapKeyboardPanDelta", "isEditableKeyboardTarget", "handleMapKeyboardPan",
        "activateMapKeyboardPan", "deactivateMapKeyboardPanOutside", "handleMapWheelZoom", "bindDebugControls",
        "mapViewBox", "mapViewportBox", "applyMapViewport", "clampMapPan", "panMap", "zoomMap", "resetMapView",
        "setMapInteractionMode", "mapPointFromPointerEvent", "boxFromPoints", "updateZoomSelectionOverlay",
        "clearZoomSelectionOverlay", "zoomMapToBox", "selectionZoomFactor", "eventScreenX", "eventScreenY",
        "zoomMapOutFromBox", "isZoomOutDrag", "beginMapPointerPan", "updateMapPointerPan",
        "finishMapPointerPan", "cancelMapPointerPan", "beginMapRectangleZoom", "updateMapRectangleZoom",
        "finishMapRectangleZoom", "cancelMapRectangleZoom",
    )) + "\n" + extract(dashboard, (
        "diagnosticRequire", "diagnosticUnavailable", "diagnosticMapInteractionRow",
        "diagnosticExerciseMapInteractionDom", "diagnosticMapInteractionRenderPolicy",
        "diagnosticDebugMapInteractionAdapter", "diagnosticDebugMapImageApproved",
        "diagnosticMapInteractionNodeVisible", "diagnosticMapInteractionSvgVectorCount",
    )) + r"""
const point=svgEl('circle',{r:5});
attachMapEvidence(point,{source_id:'cp-1',display_label:'Checkpoint',evidence_type:'candidate route'},'cp-1');
runtimeMap.appendChild(point);
const layer=svgEl('g',{'data-layer-group':'rudy-twmap'});
layer.appendChild(svgEl('image',{'data-raster-tile':'12/1/1',href:'/admin/tiles/imagery/fixture/rudy-twmap/12/1/1.png?source_id=happyman_rudy_twmap&cache_only=1&exact=1'}));
runtimeMap.appendChild(layer);
bindDebugControls();applyMapViewport();
const adapter=diagnosticDebugMapInteractionAdapter({contentDocument:document},{},'svg');
adapter.settle=async()=>{};
""" + f"const broken={json.dumps(broken)};\n" + r"""
if(broken==='zoom')document.getElementById('zoomIn').addEventListener('click',event=>event.stopImmediatePropagation(),true);
if(broken==='wheel')runtimeMap.addEventListener('wheel',event=>event.preventDefault());
if(broken==='image')runtimeMap.appendChild(svgEl('image',{href:'arbitrary.png',width:100,height:100}));
if(broken==='reverse-shrinks')runtimeMap.addEventListener('pointerup',()=>{
  const selection=debugPageState.zoomSelection;
  if(selection?.moved&&isZoomOutDrag(selection)){
    const before=debugPageState.zoom;cancelMapRectangleZoom();debugPageState.zoom=before/2;applyMapViewport();
  }
},true);
if(broken==='minus-noop')document.getElementById('zoomOut').addEventListener('click',event=>event.stopImmediatePropagation(),true);
(async()=>{
const rows=await diagnosticExerciseMapInteractionDom({id:'debug-map',renderer:'svg'},adapter);
if(!broken)for(const row of rows)assert.equal(row.status,'passed',row.check+': '+row.detail);
if(!broken)assert.equal(rows.find(row=>row.check==='DASH-027').evidence.reverseRectangleZoomIn,true);
if(broken==='zoom')assert.equal(rows.find(row=>row.check==='DASH-029').status,'failed');
if(broken==='wheel')assert.equal(rows.find(row=>row.check==='DASH-027').status,'failed');
if(broken==='image')assert.equal(rows.find(row=>row.check==='DASH-028').status,'failed');
if(['reverse-shrinks','minus-noop'].includes(broken)){
  const row=rows.find(row=>row.check==='DASH-027');assert.equal(row.status,'failed');
  const name=broken==='reverse-shrinks'?'reverse_rectangle':'minus_zoom_out';
  assert.equal(row.evidence.subchecks.find(item=>item.name===name).status,'failed');
  assert.equal(row.evidence.subchecks.find(item=>item.name==='forward_rectangle').status,'passed');
  assert.equal(row.evidence.subchecks.find(item=>item.name==='wheel_page_scroll').status,'passed');
  assert.equal(row.evidence.subchecks.find(item=>item.name==='outside_focus_key_preserved').status,'passed');
}
console.log(JSON.stringify(rows));
})().catch(error=>{console.error(error);process.exitCode=1}).finally(()=>window.close());
"""
    result = subprocess.run(["node", "-e", source], cwd=ROOT, text=True, capture_output=True, timeout=45)
    assert result.returncode == 0, result.stderr
