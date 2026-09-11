"""Behavior checks for approved Diagnostic alignment and workspace isolation."""
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / 'docs/admin/scout-dashboard-v0.1.html'


def function(name, page=PAGE):
    source = page.read_text()
    match = re.search(rf'(?ms)^    (?:async )?function {name}\(.*?^    }}', source)
    assert match, name
    return match.group()


def node(source):
    result = subprocess.run(['node'], input=source, text=True, capture_output=True, cwd=ROOT, timeout=30)
    assert result.returncode == 0, result.stderr


def test_canonical_registration_preserves_historical_layer_default_off():
    source = PAGE.read_text()
    initializer = source.split('      layerEnabled: {', 1)[1].split('\n      },', 1)[0]
    node('''const assert = require('node:assert/strict');
const SCOUT_LAYER_IDS = ['osm', 'historical-map', 'route'];
const WEATHER_LAYER_DEFAULTS = {};
const enabled = {''' + initializer + '''};
assert.equal(enabled['historical-map'], false);
assert.equal(enabled.osm, false);
assert.equal(enabled.route, true);
''')


def test_project_resolution_never_falls_back_or_adopts_another_workspace():
    node('\n'.join(function(n) for n in ['resolvedPretripProjectId', 'pretripDataProjectIds', 'fetchFirstPretripJson']) + r'''
const assert = require('node:assert/strict');
let selected = 'selected_scoutAI';
const projectId = () => selected;
const state = {pretripDataProjectId:'old_demo'};
const paths=[];
let fetchJson = async path => {paths.push(path); throw new Error('404');};
(async()=>{
 assert.deepEqual(pretripDataProjectIds(),['selected_scoutAI']);
 await assert.rejects(fetchFirstPretripJson(id=>'/projects/'+id),/404/);
 assert.deepEqual(paths,['/projects/selected_scoutAI']);
 fetchJson = async()=>({project_id:'old_demo'});
 await assert.rejects(fetchFirstPretripJson(id=>id),/does not match/);
 fetchJson = async()=>{selected='new_workspace'; return {project_id:'selected_scoutAI'};};
 await assert.rejects(fetchFirstPretripJson(id=>id),/Workspace changed/);
 fetchJson = async()=>({project_id:'new_workspace',status:'degraded'});
 assert.equal((await fetchFirstPretripJson(id=>id)).status,'degraded');
 assert.equal(state.pretripDataProjectId,'new_workspace');
})().catch(e=>{console.error(e);process.exitCode=1});
''')


def test_stale_empty_and_unavailable_are_not_green_but_authority_failures_stay_errors():
    node('\n'.join(function(n) for n in ['diagnosticAvailability','diagnosticWarning','diagnosticUnavailable','diagnosticRequire']) + r'''
const assert = require('node:assert/strict');
for(const state of ['stale_data','not_prepared','empty','unavailable','blocked','degraded']) {
 const r=diagnosticAvailability(state,'contract checked');
 assert.equal(r.status,'warning'); assert.equal(r.structureStatus,'passed'); assert.equal(r.dataStatus,state);
}
assert.equal(diagnosticAvailability('ready','ok').status,'passed');
try {diagnosticUnavailable('not_prepared','missing');} catch(e) {assert.equal(e.diagnosticStatus,'warning');}
try {diagnosticRequire(false,'authority violation');assert.fail();} catch(e) {assert.equal(e.diagnosticStatus,undefined);}
''')


def test_actual_weather_tile_url_is_cache_only_until_explicit_refresh():
    pretrip = ROOT/'docs/admin/phase4-pretrip-planning.html'
    node(function('rasterTileTemplate',pretrip) + r'''
const assert = require('node:assert/strict');
const PROJECT_ID='selected_scoutAI', HISTORICAL_MAP_LAYER_ID='historical-map';
const RASTER_WORKSPACE_CACHE_QUERY='cache_only=1', RASTER_TILE_CACHE_BUST='test';
const state={rasterRemoteRefreshEnabled:false,rasterRefreshNonce:'one'};
const rasterLayerFor=()=>({});
const rasterSourceDefinitionFor=()=>({sourceId:'happyman_rudy_twmap'});
const apiUrlTemplate=s=>s;
let url=new URL(rasterTileTemplate({},'rudy-twmap'),'http://localhost');
assert.equal(url.searchParams.get('cache_only'),'1');
assert.equal(url.searchParams.has('native'),false);
assert.equal(url.searchParams.has('refresh'),false);
assert.equal(url.searchParams.get('source_id'),'happyman_rudy_twmap');
assert.equal(url.searchParams.get('exact'),'1');
state.rasterRemoteRefreshEnabled=true;
url=new URL(rasterTileTemplate({},'rudy-twmap'),'http://localhost');
assert.equal(url.searchParams.has('cache_only'),false);
assert.equal(url.searchParams.get('native'),'1');
assert.equal(url.searchParams.get('refresh'),'1');
assert.equal(url.searchParams.get('exact'),'1');
''')


def test_rudy_detail_zoom_is_not_limited_to_prepared_coverage():
    pretrip = ROOT/'docs/admin/phase4-pretrip-planning.html'
    node('\n'.join(function(n, pretrip) for n in ['parseZoomRange', 'rasterZoomRangeFor']) + r'''
const assert = require('node:assert/strict');
const OSM_MIN_ZOOM=8, OSM_MAX_ZOOM=20, OSM_TARGET_ZOOM=14;
const clamp=(n,low,high)=>Math.min(high,Math.max(low,n));
const rasterLayerFor=()=>({raster_tile_min_zoom:8,raster_tile_max_zoom:14});
const rasterSourceDefinitionFor=id=>({sourceId:id==='rudy-twmap'?'happyman_rudy_twmap':'nlsc_photo2',maxZoom:20});
assert.deepEqual(rasterZoomRangeFor({},'rudy-twmap'),{min:8,max:20});
assert.deepEqual(rasterZoomRangeFor({},'imagery'),{min:8,max:14});
''')


def test_map_zoom_badge_tracks_camera_without_scanning_feature_collection():
    pretrip = ROOT/'docs/admin/phase4-pretrip-planning.html'
    node(function('updateMapZoomIndicator', pretrip) + r'''
const assert=require('node:assert/strict');
const nodes={zoomIn:{},zoomOut:{},zoomLevel:{},mapLibreEvidenceMap:{dataset:{}}};
const document={getElementById:id=>nodes[id]};
const state={zoom:1,mapInteractionMode:'pan',mapRenderer:{active:'maplibre'},
 mapLibreRenderer:{snapshot:()=>{throw Error('must not scan features')}}};
const MAP_MIN_ZOOM=1, mapInteractionMaxZoom=()=>8;
updateMapZoomIndicator();
assert.equal(nodes.zoomLevel.textContent,'1.00x');
updateMapZoomIndicator('',{zoom:15.675839,minZoom:0,maxZoom:22});
assert.equal(nodes.zoomLevel.textContent,'z15.7');
assert.equal(nodes.zoomIn.disabled,false);
assert.equal(nodes.zoomOut.disabled,false);
updateMapZoomIndicator('',{zoom:22,minZoom:0,maxZoom:22});
assert.equal(nodes.zoomIn.disabled,true);
''')


def test_direct_map_entry_sets_workspace_label_without_loading_other_scopes():
    render_identity = function('render').split('      destroyNavigationTerrainMapLibre();', 1)[0] + '\n    }'
    node(render_identity + function('setRoute') + r'''
const assert=require('node:assert/strict');
const nodes={dashboardRouteStatus:{textContent:'old_demo'},pageTitle:{}};
const document={getElementById:id=>nodes[id],querySelectorAll:()=>[]};
const projectId=()=> 'dongqing_batongguan_historic_trail_newImport';
const DIAGNOSTIC_MAP_PROBE=false;
const state={}, SIX_FORCES=[], routeMeta={map:['Map'],home:['Home']};
const stopLivingRefresh=()=>{};
const loadDataForRoute=()=>{throw Error('direct entry should not require this call');};
setRoute('map');
assert.equal(nodes.dashboardRouteStatus.textContent,projectId());
assert.equal(document.title,`Scout Dashboard · ${projectId()}`);
''')


def test_old_results_are_invalidated_for_all_projects_and_api_origins():
    node('\n'.join(function(n) for n in ['diagnosticCaseScopeKey','diagnosticResult']) + r'''
const assert=require('node:assert/strict');
let selected='one', base=''; const projectId=()=>selected, resolvedPretripProjectId=()=>selected, apiBase=()=>base;
const NAVIGATION_DIAGNOSTIC_CASE_IDS=[];
const state={diagnosticResults:{'DASH-031':{status:'passed',scopeKey:'|one|diagnostic-v2'}}};
assert.equal(diagnosticResult('DASH-031').status,'passed');
selected='two'; assert.equal(diagnosticResult('DASH-031').status,'idle');
selected='one'; base='http://other'; assert.equal(diagnosticResult('DASH-031').status,'idle');
''')
