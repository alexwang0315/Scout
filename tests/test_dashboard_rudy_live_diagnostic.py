"""D037 decisions and real DOM contract replay; live Chrome remains a separate run."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "docs/admin/scout-rudy-live-diagnostic.js"
PAGE = ROOT / "docs/admin/scout-dashboard-v0.1.html"


def node(program):
    executable = shutil.which("node")
    assert executable, "Node is required for the native Rudy diagnostic replay"
    result = subprocess.run([executable, "-", str(MODULE)], input=program, text=True,
                            capture_output=True, cwd=ROOT, timeout=30)
    assert result.returncode == 0, result.stderr


def function(name):
    match = re.search(rf"(?ms)^    (?:async )?function {name}\(.*?^    }}", PAGE.read_text())
    assert match, name
    return match.group()


BASE = r"""
const assert = require('node:assert/strict');
const api = require(process.argv[2]);
const project = 'diagnostic_trip', base = 'http://scout.test/admin/dashboard?projectId='+project;
const href = (z=20,x=850000,y=450000,mode='native') =>
  `http://scout.test/admin/tiles/imagery/${project}/imagery/${z}/${x}/${y}.png?source_id=happyman_rudy_twmap&exact=1&${mode}=1`;
const headers = extra => new Headers({'X-Scout-Tile-Exact':'true','X-Scout-Tile-Zoom':'20',
 'X-Scout-Imagery-Source-Id':'happyman_rudy_twmap','X-Scout-Tile-Source':'local_source_cache',...extra});
"""


def test_inventory_expands_every_entry_renderer_lens_and_daily_instance():
    node(BASE + r"""
const ids=['overview-map','lbs-map','permission-map','emergency-review-map','architecture-map','pace-fit-map',
 'map','weather-map','navigation-map','debug-map','permission-day-maps'];
const cases=api.casesFor(ids.map(id=>({id})), ['day-a','day-b','day-a']);
assert.equal(cases.length,38);
for(const id of ['map','weather-map','debug-map'])
 assert.deepEqual(cases.filter(c=>c.id===id).map(c=>c.renderer),['maplibre','svg']);
assert.equal(cases.filter(c=>c.id==='architecture-map').length,7);
assert.ok(cases.some(c=>c.id==='architecture-map'&&c.variant==='time_window'));
const navigation=cases.filter(c=>c.id==='navigation-map');
assert.equal(navigation.length,18);
assert.equal(navigation.filter(c=>c.auditNavigationDomains).length,1);
assert.ok(navigation.every(c=>c.variant.startsWith(c.domain+':')));
assert.deepEqual(navigation.filter(c=>c.variant.includes(':loading:')).map(c=>c.domain),['observed','terrain','prior']);
assert.ok(navigation.filter(c=>!c.variant.includes(':loading:')).every(c=>c.domain==='observed'));
assert.equal(api.casesFor(ids.map(id=>({id})),Array.from({length:9},(_,index)=>'D'+(index+1))).length,45);
assert.equal(cases.filter(c=>c.id==='permission-day-maps').length,2);
assert.throws(()=>api.casesFor(ids.slice(1).map(id=>({id})),[]),/inventory missing/);
assert.throws(()=>api.casesFor([...ids,'new-rudy-map'].map(id=>({id})),[]),/unmapped entry/);
assert.equal(api.STAGES.length,10);
assert.deepEqual(api.STAGES,['initial','reload','fit','first-plus','native-z20','actual-maximum','pan-z20','cache-hit','cache-miss','recovery']);
""")


def navigation_dom_program():
    # Execute the actual domain switches, source/style builders, SVG ready and
    # loading renderers. Empty terrain geometry keeps this source-inventory
    # replay independent of tiles/network; it is not a native completion proof.
    program = BASE + r"""
const {JSDOM}=require('jsdom');
const dom=new JSDOM('<main id="workspace"></main>',{url:base});
const document=dom.window.document,DOMParser=dom.window.DOMParser;
const state={navigationTerrainEvidenceDomain:'prior',navigationTerrainLens:'events',navigationTerrainViewMode:'split'};
const originalState=structuredClone(state),asArray=value=>Array.isArray(value)?value:[];
const escapeHtml=value=>String(value??''),valueOrDash=escapeHtml,formatInteger=escapeHtml,formatDistanceKm=escapeHtml;
const diagnosticRequire=(value,message)=>{if(!value)throw Error(message)};
const bounds={west:120,east:121,north:24,south:23};
const snapshot={status:'ready',orientation_basemap:{status:'ready',bounds_wgs84:bounds},
 terrain_surface:{bbox_wgs84:bounds},terrain_raster_dem:{status:'ready',bounds_wgs84:bounds,tile_url_template:'/dem/{z}/{x}/{y}.png',minzoom:12,maxzoom:14}};
const NAVIGATION_RUDY_TILE_SOURCE={minZoom:5,maxZoom:20},NAVIGATION_TERRAIN_ROUTE_CORRIDOR_MODES=[];
const DASHBOARD_MAP_RENDER_POLICY={},QGIS_GOLDEN_ROUTE_CONTACT_DISTANCE_M=30;
const navigationRudyBounds=value=>value,navigationRudyBaseZoom=()=>12,dashboardRudyPaddedBounds=value=>value;
const renderNavigationRudyTileLayer=()=>'<g data-dashboard-rudy-tile-layer="true"></g>';
const renderNavigationTerrainTopDownLayer=()=>'<g data-dem-derived="true"></g>';
const renderDashboardMapViewport=(id,label,content,options)=>`<div id="${id}" data-dashboard-map-viewport="${id}" ${options.attributes}>${content}</div>`;
const emptyCollection=()=>({type:'FeatureCollection',features:[]});
const navigationTerrainMapLibreFeatureCollection=emptyCollection,navigationTerrainKnownGpxReferenceFeatureCollection=emptyCollection;
const navigationTerrainMapLibreEventFeatureCollection=emptyCollection,navigationTerrainRouteConsistencyFeatureCollection=emptyCollection;
const navigationTerrainRouteHypothesisFeatureCollection=emptyCollection,qgisTerrainRouteDraftFeatureCollection=emptyCollection;
const terrainRouteGuidanceFeatureCollection=emptyCollection;
const navigationTerrainRasterImageSource=()=>null,navigationTerrainRasterOverlay=()=>null;
const navigationTerrainRouteHypothesis=()=>null,navigationTerrainRouteHypothesisBand=()=>'',navigationTerrainRouteHypothesisOverlay=()=>null;
const navigationTerrainRouteHypothesisImageSource=()=>null,navigationTerrainRouteHypothesisDisplayLabel=()=>'';
const navigationTerrainRouteHypothesisBandLabel=()=>'',navigationTerrainRouteHypothesisOptions=()=>[],navigationTerrainRouteHypothesisSelectionId=()=>'';
const navigationTerrainLayerVisible=()=>true,navigationTerrainRudyOpacity=()=>1,navigationTerrainRasterOpacity=()=>1;
const navigationTerrainRudyTileTemplate=()=>href().replace('/20/850000/450000.png','/{z}/{x}/{y}.png');
const navigationTerrainMapLayerKey=()=>null,navigationTerrainLayerVisibility=()=>({});
const navigationTerrainDemReady=()=>true,navigationTerrainCameraMinimumZoom=()=>12;
const navigationTerrainRouteDemCoverage=()=>({status:'supported',totalCount:0}),navigationTerrainRouteDemCoverageText=()=>'';
const navigationTerrainInterpolationText=()=>'',navigationTerrainCandidateScope=()=> 'route',navigationTerrainVisualPreset=()=> 'rudy';
const navigationTerrainLensLabel=value=>value,navigationTerrainMapLibreLensSummary=()=>({qgis_count:0});
const navigationTerrainMapLibreVisibilitySummary=()=>({}),navigationTerrainUsesStandardGrass=()=>false;
const qgisSpatialOutwardCandidateCounts=()=>({total:0}),qgisTerrainRouteSelectionTarget=()=>'';
const qgisSpatialWorkflowFeatures=()=>[]; // This source-inventory fixture has no prepared QGIS geometry.
const qgisSpatialRouteFilterSummary=()=>({connected_counts:{},raw_counts:{}}),renderQgisTerrainRouteBuilder=()=>'';
const navigationTerrainPressureSamples=()=>[],navigationTerrainRoutePath=()=>'';
const navigationTerrainEventLocationSummary=()=>({locations:[]}),navigationTerrainEventLocationForEvent=()=>null;
const registry=['overview-map','lbs-map','permission-map','emergency-review-map','architecture-map','pace-fit-map',
 'map','weather-map','navigation-map','debug-map','permission-day-maps'].map(id=>({id}));
const cases=api.casesFor(registry,['D1']);
"""
    for name in ["navigationTerrainWorkspaceSelection", "renderNavigationQgisTerrainOverlay", "qgisSpatialMaplibreFeatures",
                 "navigationTerrainEvidenceDomain", "navigationTerrainMapLibreStyle",
                 "renderNavigationTerrainMapLibreHost", "renderNavigationTerrainReviewWorkbench",
                 "renderNavigationWorkspaceMap", "renderNavigationWorkspaceLoading",
                 "diagnosticNavigationRudyDomainEvidence"]:
        program += function(name) + "\n"
    return program


def test_navigation_production_sources_cover_all_loading_domains_and_isolate_ready_domains():
    node(navigation_dom_program() + r"""
const evidence=diagnosticNavigationRudyDomainEvidence(snapshot);
assert.deepEqual(state,originalState,'Inventory rendering must restore the selected domain/lens/view');
assert.equal(evidence.rows.length,12);
assert.equal(api.validateNavigationCoverage(evidence,cases).status,'passed');
assert.deepEqual(evidence.domains,['terrain','observed','prior'],'Domains come from production controls');
for(const row of evidence.rows){
 assert.equal(row.hasRudy,row.domain==='observed'||row.mode==='loading');
 if(row.mode==='loading')assert.equal(row.renderedDomain,null,'The production orientation shell is domain-independent');
 else assert.equal(row.renderedDomain,row.domain);
}
const originalStyle=navigationTerrainMapLibreStyle;
navigationTerrainMapLibreStyle=(snapshot,mode)=>{
 const style=originalStyle(snapshot,mode);
 if(state.navigationTerrainEvidenceDomain==='terrain'){
  style.sources['new-rudy-source']={type:'raster',tiles:[navigationTerrainRudyTileTemplate()]};
  style.layers.push({id:'new-rudy-layer',source:'new-rudy-source',type:'raster'});
 }
 return style;
};
const drift=diagnosticNavigationRudyDomainEvidence(snapshot);
assert.ok(drift.rows.find(row=>row.domain==='terrain'&&row.mode==='2d').rudySources.includes('new-rudy-source'));
assert.throws(()=>api.validateNavigationCoverage(drift,cases),/actual source and declared basemap disagree/);
assert.deepEqual(state,originalState);
dom.window.close();
""")


@pytest.mark.parametrize("drift", ["terrain-rudy", "prior-rudy", "missing-loading-case", "missing-mode",
                                    "wrong-domain", "new-control", "missing-evidence"])
def test_new_or_unlisted_navigation_rudy_source_cannot_pass_native_matrix(drift):
    node(navigation_dom_program() + r"""
const evidence=diagnosticNavigationRudyDomainEvidence(snapshot),drift=DRIFT;
let tested=cases;
if(drift==='terrain-rudy'||drift==='prior-rudy'){
 const row=evidence.rows.find(row=>row.domain===drift.split('-')[0]&&row.mode==='2d');
 row.hasRudy=true;row.declaredBasemap='rudy-twmap';
}else if(drift==='missing-loading-case')tested=cases.filter(item=>item.variant!=='terrain:loading:structure');
else if(drift==='missing-mode')evidence.rows.pop();
else if(drift==='wrong-domain')evidence.rows[0].renderedDomain='observed';
else if(drift==='new-control')evidence.domains.push('new-domain');
else delete evidence.rows;
assert.throws(()=>api.validateNavigationCoverage(evidence,tested));
const testCase=cases.find(item=>item.auditNavigationDomains);
(async()=>{
 const result=await api.runCase(testCase,{projectId:project,inventoryCases:tested,open:async()=>({
  descriptor:{navigationDomainEvidence:evidence,snapshot:()=>({matrix:20,verified:20})},
  close:async()=>({disposed:true,activeMaps:0,pendingInitializations:0,errors:[]})})});
 assert.equal(result.status,'warning');assert.equal(result.stages[0].stage,'initial');
 assert.equal(result.stages[0].status,'warning');assert.equal(result.stages.filter(stage=>stage.status==='passed').length,0);
 assert.deepEqual(result.navigationDomainEvidence,evidence,'Retain the mismatched source evidence for review');
 dom.window.close();
})().catch(error=>{console.error(error);process.exitCode=1});
""".replace("DRIFT", json.dumps(drift)))


def test_navigation_domain_mismatch_invalidates_otherwise_complete_tiles():
    node(BASE + r"""
const {JSDOM}=require('jsdom');
const dom=new JSDOM('<div id="viewport" data-navigation-evidence-domain="observed"></div>',{url:base});
const doc=dom.window.document,root=doc.querySelector('#viewport');
Object.assign(root.dataset,{dashboardTileRequestedZoom:'20',dashboardTileVerifiedZoom:'20',dashboardTileLoadState:'ready',
 dashboardTileRequiredCount:'1',dashboardTileSuccessCount:'1',dashboardTilePendingCount:'0',dashboardTileErrorCount:'0',dashboardTileUnverifiedCount:'0'});
root.dashboardMapController={getState:()=>({zoom:256})};
let current='observed';
const descriptor=api.descriptorFor({kind:'dashboard-svg',renderer:'svg',root,doc,projectId:()=>project,
 navigationDomain:'observed',navigationDomainState:()=>current,navigationPhase:'ready'});
assert.equal(api.nativeComplete(descriptor.snapshot()),true);
current='terrain';assert.equal(api.nativeComplete(descriptor.snapshot()),false);
current='observed';root.dataset.navigationEvidenceDomain='prior';
assert.equal(api.nativeComplete(descriptor.snapshot()),false);
delete root.dataset.navigationEvidenceDomain;root.dataset.navigationEvidenceState='loading';
const loading=api.descriptorFor({kind:'dashboard-svg',renderer:'svg',root,doc,projectId:()=>project,
 navigationDomain:'terrain',navigationDomainState:()=>current,navigationPhase:'loading'});
assert.equal(api.nativeComplete(loading.snapshot()),false);
current='terrain';assert.equal(api.nativeComplete(loading.snapshot()),true);
assert.deepEqual(loading.snapshot().navigationDomain,{requested:'terrain',state:'terrain',rendered:null,phase:'loading',renderedState:'loading'});
dom.window.close();
""")


def test_entry_preparation_keeps_each_navigation_domain_and_loading_variant():
    node(navigation_dom_program() + r"""
dom.reconfigure({url:base+'&diagnosticMapProbe=1&diagnosticNativeTiles=1'});
const location=dom.window.location,DIAGNOSTIC_MAP_PROBE=true,projectId=()=>project;
const diagnosticRudySurfaces=()=>[{id:'navigation-map',family:'navigation',route:'outdoor-navigation',label:'Navigation'}];
const loadDataScope=async()=>{},stopNavigationTerrainPolling=()=>{},navigationTerrainSnapshot=()=>snapshot;
const navigationTerrainMapLibreRuntime={maps:[]};
const initializeNavigationTerrainMapLibre=async()=>{
 const host=document.querySelector('[data-navigation-maplibre-map]');
 navigationTerrainMapLibreRuntime.maps=[{mode:host.dataset.navigationMaplibreMap,host,map:{}}];
};
const diagnosticWaitForMapOrder=async predicate=>{const result=predicate();assert.ok(result);return result};
const bindDashboardMapViewports=()=>{
 for(const viewport of document.querySelectorAll('[data-dashboard-map-viewport]'))viewport.dashboardMapController={getState:()=>({zoom:1})};
};
""" + function("diagnosticPrepareRudyEntry") + r"""
(async()=>{
 for(const testCase of cases.filter(item=>item.id==='navigation-map')){
  const config=await diagnosticPrepareRudyEntry(testCase,{projectId:project});
  assert.equal(config.navigationDomain,testCase.domain);
  assert.equal(config.navigationDomainState(),testCase.domain);
  assert.equal(config.root.isConnected,true);
  if(testCase.variant.includes(':loading:')){
   assert.equal(config.navigationPhase,'loading');
   assert.equal(config.root.dataset.navigationEvidenceState,'loading');
   assert.ok(config.root.querySelector('[data-dashboard-rudy-tile-layer="true"]'));
  }else assert.equal(config.root.dataset.navigationEvidenceDomain,'observed');
  if(testCase.auditNavigationDomains)assert.equal(api.validateNavigationCoverage(config.navigationDomainEvidence,cases).status,'passed');
 }
 await assert.rejects(diagnosticPrepareRudyEntry({id:'navigation-map',renderer:'svg',domain:'terrain',variant:'terrain:fallback:structure'},
  {projectId:project}),/Unknown Navigation Rudy domain/);
 dom.window.close();
})().catch(error=>{console.error(error);process.exitCode=1});
""")


def test_architecture_inventory_matches_real_production_lens_controls_including_time_window():
    node(BASE + r"""
const {JSDOM}=require('jsdom');
const dom=new JSDOM('<main></main>',{url:base}),doc=dom.window.document;
const state={architectureLens:'time_window'},MAP_WIDTH=1000,MAP_HEIGHT=392,DASHBOARD_MAP_RENDER_POLICY={};
const escapeHtml=value=>String(value??''),formatInteger=escapeHtml;
const buildMapData=()=>({bounds:{west:120,east:121,north:24,south:23},coordinateSegments:[],connected:true});
const architectureBins=()=>[{end_distance_m:100}],architectureSelectedBin=()=>null;
const dashboardRudyPaddedBounds=value=>value,navigationRudyBaseZoom=()=>12;
const dashboardMapPathFromSegments=()=>'',architectureMapSlices=()=>'',architectureMapCheckpointPoints=()=>'';
const architectureLensLabel=value=>value,architectureLensLegendSubtitle=()=>'',renderArchitectureLensLegend=()=>'';
const renderDashboardRudyTileLayer=()=>'<g data-dashboard-rudy-tile-layer="true"></g>';
const renderDashboardMapViewport=(id,label,content)=>`<div data-dashboard-map-viewport="${id}">${content}</div>`;
""" + function("renderArchitectureMap") + r"""
doc.querySelector('main').innerHTML=renderArchitectureMap({});
const buttons=[...doc.querySelectorAll('button[data-architecture-lens]')];
const lenses=buttons.map(button=>button.dataset.architectureLens);
const registry=['overview-map','lbs-map','permission-map','emergency-review-map','architecture-map','pace-fit-map',
 'map','weather-map','navigation-map','debug-map','permission-day-maps'].map(id=>({id}));
const cases=api.casesFor(registry,['D1']);
assert.equal(api.validateArchitectureCoverage(lenses,cases).status,'passed');
const selected=buttons.find(button=>button.getAttribute('aria-selected')==='true');
assert.equal(selected.dataset.architectureLens,'time_window');assert.equal(selected.disabled,false);
assert.throws(()=>api.validateArchitectureCoverage(lenses,cases.filter(item=>item.variant!=='time_window')),/production lens controls differ/);
assert.throws(()=>api.validateArchitectureCoverage([...lenses,'new-lens'],cases),/production lens controls differ/);
dom.window.close();
""")


@pytest.mark.parametrize("patch", [
    {"verified": 19}, {"required": 0, "success": 0}, {"success": 3},
    {"pending": 1}, {"errors": 1}, {"unverified": 1}, {"unverified": None},
    {"rendererReady": False}, {"status": "retained-previous"}, {"failure": "native-load-error"},
])
def test_available_or_high_camera_zoom_cannot_hide_incomplete_native_tiles(patch):
    node(BASE + r"""
const complete={rendererReady:true,matrix:20,verified:20,required:4,success:4,pending:0,
 errors:0,unverified:0,status:'available',failure:''};
assert.equal(api.nativeComplete(complete,20),true);
assert.equal(api.nativeComplete({...complete,...""" + json.dumps(patch) + r"""},20),false);
""")


def test_actual_maximum_requires_pixel_scale_and_unclamped_native_coverage():
    node(BASE + r"""
const camera={active:true,layerId:'rudy-twmap',providerNativeMaxZoom:20,nativeTileSize:256,worldTileSize:512,
 cameraZoom:19,maxCameraZoom:19,worldPixelsPerProviderPixel:1,pixelScaleScope:'unpitched-camera-pixel-scale',
 requestedNativeZooms:[20],requestedAboveNativeMax:false};
const complete={activeRenderer:'maplibre',rendererReady:true,matrix:20,verified:20,required:4,success:4,pending:0,
 errors:0,unverified:0,status:'available',failure:'',viewLimits:{viewZoom:19,maxViewZoom:19,nativePixelRatio:1,nativeCamera:camera}};
assert.equal(api.maximumComplete(complete),true);
assert.equal(api.maximumComplete({...complete,viewLimits:{...complete.viewLimits,viewZoom:18.814}}),false,
 'First native Z20 is not proof that the actual interaction maximum was tested');
assert.equal(api.maximumComplete({...complete,viewLimits:{viewZoom:22,maxViewZoom:22,nativePixelRatio:8,
 nativeCamera:{...camera,cameraZoom:22,maxCameraZoom:22,worldPixelsPerProviderPixel:8}}}),false,
 'All Z20 tiles can load while the camera magnifies each original pixel eightfold');
for(const patch of [{requestedAboveNativeMax:null},{requestedAboveNativeMax:true,requestedNativeZooms:[20,21]},
 {requestedNativeZooms:[]},{cameraZoom:18},{maxCameraZoom:22},{active:false}])
 assert.equal(api.maximumComplete({...complete,viewLimits:{...complete.viewLimits,nativeCamera:{...camera,...patch}}}),false);
// At pitch, world scale alone is insufficient: the public, unclamped covering
// cohort must independently remain within the provider's native ceiling.
assert.equal(api.maximumComplete({...complete,viewLimits:{...complete.viewLimits,
 nativeCamera:{...camera,pitch:52,pixelScaleScope:'camera-world-scale-only',requestedNativeZooms:[19,20]}}}),true);
assert.equal(api.maximumComplete({...complete,viewLimits:{...complete.viewLimits,
 nativeCamera:{...camera,pitch:52,pixelScaleScope:'camera-world-scale-only',requestedAboveNativeMax:null}}}),false);
""")


def test_svg_actual_maximum_measures_original_tile_css_pixels_not_disabled_button():
    node(BASE + r"""
const {JSDOM}=require('jsdom');
const dom=new JSDOM(`<div id="viewport" data-dashboard-map-viewport="daily" data-map-max-zoom="256"
 data-dashboard-tile-requested-zoom="20" data-dashboard-tile-verified-zoom="20" data-dashboard-tile-load-state="ready"
 data-dashboard-tile-required-count="1" data-dashboard-tile-success-count="1" data-dashboard-tile-pending-count="0"
 data-dashboard-tile-error-count="0" data-dashboard-tile-unverified-count="0">
 <button data-map-control="zoom-in" disabled>+</button><svg><g data-dashboard-rudy-tile-layer="true">
 <image data-dashboard-rudy-tile="20/850000/450000" href="${href()}"/></g></svg></div>`,{url:base});
const doc=dom.window.document,root=doc.querySelector('#viewport'),image=root.querySelector('image');
root.dashboardMapController={getState:()=>({zoom:256,x:0,y:0})};
let width=213.722656;image.getBoundingClientRect=()=>({width,height:width});
const descriptor=api.descriptorFor({kind:'dashboard-svg',renderer:'svg',root,doc,projectId:()=>project});
let snapshot=descriptor.snapshot();assert.equal(api.maximumComplete(snapshot),true);
assert.equal(snapshot.viewLimits.nativePixelRatio,width/256);assert.equal(snapshot.viewLimits.measuredTileCount,1);
width=2048;snapshot=descriptor.snapshot();assert.equal(api.nativeComplete(snapshot),true);
assert.equal(api.maximumComplete(snapshot),false,'Native20 success and a disabled + still cannot conceal 8x pixels');
width=0;assert.equal(api.maximumComplete(descriptor.snapshot()),false,'Invisible tiles have no pixel measurement');
width=256;delete root.dataset.mapMaxZoom;assert.equal(api.maximumComplete(descriptor.snapshot()),false);
dom.window.close();
""")


def test_pretrip_maximum_reads_public_bridge_and_keeps_camera_receipt_in_snapshot():
    node(BASE + r"""
const {JSDOM}=require('jsdom');
const dom=new JSDOM('<div id="mapRendererShell" data-map-renderer-active="maplibre" data-map-renderer-state="ready"><div id="host"></div></div>',{url:base});
const doc=dom.window.document,root=doc.querySelector('#host');
Object.assign(root.dataset,{maplibreRasterNativeZoom:'20',maplibreRasterVerifiedNativeZoom:'20',maplibreRasterRequiredCount:'1',
 maplibreRasterSuccessCount:'1',maplibreRasterPendingCount:'0',maplibreRasterErrorCount:'0',maplibreRasterUnverifiedCount:'0',
 maplibreRasterState:'available',maplibreRasterTransport:'same-origin-protocol'});
const camera={active:true,layerId:'rudy-twmap',providerNativeMaxZoom:20,cameraZoom:19,maxCameraZoom:19,
 worldPixelsPerProviderPixel:1,pixelScaleScope:'unpitched-camera-pixel-scale',requestedNativeZooms:[20],requestedAboveNativeMax:false};
let calls=0;const descriptor=api.descriptorFor({kind:'pretrip',renderer:'maplibre',root,doc,projectId:()=>project,
 viewLimits:()=>{calls++;return {viewZoom:19,maxViewZoom:19,nativeCamera:camera}}});
assert.equal(api.maximumComplete(descriptor.snapshot()),true);assert.equal(calls,1);
assert.deepEqual(descriptor.snapshot().viewLimits.nativeCamera,camera);
const fallback=api.descriptorFor({kind:'pretrip',renderer:'maplibre',root,doc,projectId:()=>project});
root.dataset.maplibreNativeCameraReceipt=JSON.stringify(camera);
assert.equal(api.maximumComplete(fallback.snapshot()),true);
root.dataset.maplibreNativeCameraReceipt='invalid';assert.equal(api.maximumComplete(fallback.snapshot()),false);
dom.window.close();
""")


def test_tile_url_enforces_same_workspace_exact_source_and_no_forced_refresh():
    node(BASE + r"""
assert.equal(new URL(api.tileUrl(href(),base,project,'cache').href).searchParams.get('cache_only'),'1');
assert.equal(new URL(api.tileUrl(href(),base,project,'cache').href).searchParams.has('native'),false);
for(const value of [href().replace('scout.test','other.test'),href().replace(project,'other_trip'),
 href().replace('happyman_rudy_twmap','other_source'),href()+'&refresh=1',href()+'&cache_only=1',
 href().replace('exact=1','exact=0'),href(21),href(20,2**20)])
 assert.throws(()=>api.tileUrl(value,base,project));
""")


def test_http_cache_missing_and_parent_provenance_are_distinct_from_native_success():
    node(BASE + r"""
(async()=>{
const descriptor={doc:{location:{href:base}}}; let calls=[],closed=0;
global.createImageBitmap=async()=>({width:256,height:256,close(){closed++}});
global.fetch=async(url,options)=>{calls.push({url,options});return {ok:true,status:200,headers:headers(),blob:async()=>new Blob(['png'])}};
const good=await api.readTile(href(),descriptor,project);
assert.equal(good.decoded,true);assert.equal(closed,1);
assert.equal(calls[0].options.credentials,'same-origin');assert.equal(calls[0].options.redirect,'error');
assert.equal(new URL(calls[0].url).searchParams.has('native'),false);
global.fetch=async()=>({ok:false,status:404});
assert.equal((await api.readTile(href(),descriptor,project,{allowMissing:true})).status,404);
await assert.rejects(api.readTile(href(),descriptor,project),/HTTP 404/);
for(const extra of [{'X-Scout-Tile-Source':'parent_cache_fallback'}, {'X-Scout-Tile-Exact':'false'},
 {'X-Scout-Tile-Zoom':'19'},{'X-Scout-Imagery-Source-Id':'other'}]){
 global.fetch=async()=>({ok:true,status:200,headers:headers(extra),blob:async()=>new Blob(['png'])});
 await assert.rejects(api.readTile(href(),descriptor,project),/provenance/);
}
global.fetch=async()=>({ok:true,status:200,headers:headers(),blob:async()=>new Blob(['png'])});
global.createImageBitmap=async()=>({width:1,height:1,close(){closed++}});
await assert.rejects(api.readTile(href(),descriptor,project),/256 px detail/);
assert.equal(closed,2);
})().catch(error=>{console.error(error);process.exitCode=1});
""")


def test_real_dom_reads_only_rudy_and_keeps_pending_generation_unverified():
    node(BASE + r"""
const {JSDOM}=require('jsdom');
const dom=new JSDOM(`<div id="mapRendererShell" data-map-renderer-active="svg" data-map-renderer-state="ready"></div>
<svg id="map" viewBox="0 0 1000 720"><g data-layer-group="imagery"><image data-raster-tile="20/1/1"/></g>
<g data-layer-group="rudy-twmap" data-requested-tile-zoom="19" data-displayed-tile-zoom="19" data-tile-generation-state="loading">
<g data-tile-generation="active"><image data-raster-tile="19/425000/225000" data-tile-generation-loaded="true" href="${href(19,425000,225000)}"/></g>
<g data-tile-generation="pending"><image data-raster-tile="20/850000/450000" href="${href()}"/>
<image data-raster-tile="20/850001/450000" data-tile-generation-loaded="true" href="${href(20,850001,450000)}"/></g></g></svg>`,{url:base});
const doc=dom.window.document;
const descriptor=api.descriptorFor({kind:'pretrip',renderer:'svg',root:doc.querySelector('#map'),doc,projectId:()=>project});
const snapshot=descriptor.snapshot();
assert.equal(snapshot.required,2);assert.equal(snapshot.success,1);assert.equal(snapshot.pending,1);
assert.equal(snapshot.matrix,20);assert.equal(snapshot.verified,19);
assert.equal(snapshot.scrollTop,0);assert.equal(snapshot.scrollLeft,0);
assert.equal(snapshot.tiles[0].key,'19/425000/225000');
assert.equal(api.nativeComplete(snapshot,20),false);
dom.window.close();
""")


def test_initial_svg_ready_label_cannot_substitute_for_loaded_native_cohort():
    node(BASE + r"""
const {JSDOM}=require('jsdom');
const dom=new JSDOM('<div id="mapRendererShell" data-map-renderer-active="svg" data-map-renderer-state="ready"></div><svg id="map" viewBox="0 0 1000 720"><g data-layer-group="rudy-twmap" data-requested-tile-zoom="12" data-displayed-tile-zoom="12" data-tile-generation-state="ready"></g></svg>',{url:base});
const doc=dom.window.document,root=doc.querySelector('#map'),group=root.querySelector('g');
group.innerHTML=Array.from({length:15},(_,index)=>`<image data-raster-tile="12/${3300+index}/1900" href="${href(12,3300+index,1900)}"/>`).join('');
const descriptor=api.descriptorFor({kind:'pretrip',renderer:'svg',root,doc,projectId:()=>project});
let snapshot=descriptor.snapshot();assert.equal(snapshot.status,'ready');assert.equal(snapshot.success,0);
assert.equal(snapshot.required,15);assert.equal(snapshot.unverified,15);assert.equal(api.nativeComplete(snapshot),false);
// The UI must supply tracked load receipts; an unrelated GET or unobserved
// image event cannot retroactively certify the visible initial generation.
const images=[...group.querySelectorAll('image')];images.forEach(image=>image.dispatchEvent(new dom.window.Event('load')));
assert.equal(descriptor.snapshot().success,0);
images.slice(0,14).forEach(image=>{image.dataset.tileGenerationLoaded='true'});
snapshot=descriptor.snapshot();assert.equal(snapshot.success,14);assert.equal(snapshot.unverified,1);assert.equal(api.nativeComplete(snapshot),false);
images[14].dataset.tileGenerationLoaded='true';assert.equal(api.nativeComplete(descriptor.snapshot()),true);
dom.window.close();
""")


def test_3d_native_cohort_all_levels_must_be_verified_and_urls_match_real_tiles():
    node(BASE + r"""
const {JSDOM}=require('jsdom');
const dom=new JSDOM('<section data-navigation-maplibre-shell="3d"><div id="host" data-navigation-maplibre-status="ready"></div></section>',{url:base});
const doc=dom.window.document,host=doc.querySelector('#host');
Object.assign(host.dataset,{maplibreRasterNativeZoom:'20',maplibreRasterVerifiedNativeZoom:'20',
 maplibreRasterRequiredCount:'2',maplibreRasterSuccessCount:'2',maplibreRasterPendingCount:'0',
 maplibreRasterErrorCount:'0',maplibreRasterUnverifiedCount:'0',maplibreRasterState:'available',
 maplibreRasterTransport:'same-origin-protocol',maplibreRasterNativeZooms:'19,20',maplibreRasterVerifiedNativeZooms:'20'});
const view={bounds:{west:121,south:23,east:122,north:24},tileTemplate:href().replace('/20/850000/450000.png','/{z}/{x}/{y}.png'),
 tiles:[{z:19,x:425000,y:225000},{z:20,x:850000,y:450000}]};
const descriptor=api.descriptorFor({kind:'navigation',renderer:'maplibre',root:host,doc,projectId:()=>project,tileView:()=>view});
assert.equal(api.nativeComplete(descriptor.snapshot(),20),false);
host.dataset.maplibreRasterVerifiedNativeZooms='19,20';
const snapshot=descriptor.snapshot();assert.equal(api.nativeComplete(snapshot,20),true);
host.dataset.maplibreRasterTransport='event-only';
assert.equal(api.nativeComplete(descriptor.snapshot(),20),false);
host.dataset.maplibreRasterTransport='same-origin-protocol';
assert.deepEqual(api.urlsFor(descriptor,snapshot,project).map(tile=>tile.z),[19,20]);
assert.throws(()=>api.urlsFor(descriptor,{...snapshot,required:3},project),/coverage disagrees/);
assert.equal(api.containsTile(view,{z:20,x:850000,y:450000}),true);
assert.equal(api.containsTile(view,{z:20,x:850001,y:450000}),false);
dom.window.close();
""")


def test_pan_event_reaches_vendored_maplibre_keyboard_handler_without_rotation():
    node(BASE + r"""
(async()=>{
const {JSDOM}=require('jsdom');
const {pathToFileURL}=require('node:url'),path=require('node:path');
const {KeyboardHandler}=await import(pathToFileURL(path.join(path.dirname(process.argv[2]),'vendor/maplibre-gl/6.2.0/maplibre-gl.mjs')));
const dom=new JSDOM('<section data-navigation-maplibre-shell="2d"><div id="host"><canvas tabindex="0"></canvas></div></section>',{url:base});
const doc=dom.window.document,root=doc.querySelector('#host'),canvas=root.querySelector('canvas');
const handler=new KeyboardHandler(null,{zoom:19,bearing:0,pitch:0,center:[121,23]});
let motion;
canvas.addEventListener('keydown',event=>{
 assert.equal(event.key,'ArrowRight');assert.equal(event.keyCode,39);assert.equal(event.shiftKey,false);
 const result=handler.keydown(event);assert.ok(result?.cameraAnimation);
 result.cameraAnimation({easeTo(options){motion=options}});
});
const descriptor=api.descriptorFor({kind:'navigation',renderer:'maplibre',root,doc,projectId:()=>project});
descriptor.act('right');
assert.equal(motion.offset[0],-100);assert.equal(Math.abs(motion.offset[1]),0);
assert.equal(motion.bearing,0);assert.equal(motion.pitch,0);
dom.window.close();
})().catch(error=>{console.error(error);process.exitCode=1});
""")


def test_3d_missing_tile_pan_follows_screen_projection_instead_of_world_direction():
    node(BASE + r"""
const {JSDOM}=require('jsdom');
const dom=new JSDOM('<section data-navigation-maplibre-shell="3d"><div id="host"></div></section>',{url:base});
const doc=dom.window.document,root=doc.querySelector('#host');
const descriptor=api.descriptorFor({kind:'navigation',renderer:'maplibre',root,doc,projectId:()=>project,
 map:{project:([lon,lat])=>({x:lat,y:lon})},
 tileView:()=>({tileTemplate:href(),bounds:{west:121,east:122,north:24,south:23},tiles:[{z:20,x:850000,y:450000}]})});
assert.equal(descriptor.directionTo({z:20,x:850001,y:450000,direction:'right'}),'down');
dom.window.close();
""")


def test_037_extends_its_inventory_without_mutating_layer_order_registry():
    node(BASE + r"""
const DASHBOARD_MAP_ORDER_SURFACES=Object.freeze(['overview-map','lbs-map','permission-map','emergency-review-map',
 'architecture-map','pace-fit-map','map','weather-map','navigation-map'].map(id=>Object.freeze({id})));
""" + function("diagnosticRudySurfaces") + r"""
const surfaces=diagnosticRudySurfaces();
assert.equal(surfaces.length,11);assert.equal(DASHBOARD_MAP_ORDER_SURFACES.length,9);
assert.equal(api.casesFor(surfaces,['D1']).length,37);
assert.equal(surfaces.find(item=>item.id==='debug-map').family,'canonical-debug');
assert.equal(surfaces.find(item=>item.id==='permission-day-maps').family,'permission-days');
""")


def test_approved_weather_contract_accepts_current_pretrip_source():
    node(BASE + r"""
const fs=require('node:fs'),path=require('node:path');
const diagnosticRequire=(value,message)=>{if(!value)throw Error(message)};
""" + function("diagnosticWeatherRudyTileContract") + r"""
const source=fs.readFileSync(path.join(path.dirname(process.argv[2]),'phase4-pretrip-planning.html'),'utf8');
const report=diagnosticWeatherRudyTileContract(source);
assert.equal(report.label,'Weather');assert.equal(report.configuredMaxMatrix,20);
const alternate=source.replace('Math.ceil(Math.log2(worldPixelsAtFit / 256)) + Math.ceil(Math.log2(Math.max(1, state.zoom)))','alternatePixelDensityPolicy(view, state)');
assert.deepEqual(diagnosticWeatherRudyTileContract(alternate),report,'Equivalent selector implementations must be judged by live results, not source formulas');
""")


WORKFLOW = r"""
const realTimeout=global.setTimeout; let time=0;
Date.now=()=>time;
global.setTimeout=(fn,ms)=>{if(ms<1000){time+=ms;return realTimeout(fn,0)}return realTimeout(fn,ms)};
const api=require(process.argv[2]), assert=require('node:assert/strict');
const project='diagnostic_trip',base='http://scout.test/admin/dashboard?projectId='+project;
const behavior=BEHAVIOR;
let opened=0,closed=0,actions=[],cached=new Set();
const tileId=(z,x,y)=>`${z}/${x}/${y}`;
const template=`http://scout.test/admin/tiles/imagery/${project}/imagery/{z}/{x}/{y}.png?source_id=happyman_rudy_twmap&exact=1&native=1`;
const lon=(x,z)=>(x/(2**z))*360-180;
const lat=(y,z)=>Math.atan(Math.sinh(Math.PI*(1-2*y/(2**z))))*180/Math.PI;
global.createImageBitmap=async()=>({width:256,height:256,close(){}});
global.fetch=async url=>{
 const parts=new URL(url).pathname.match(/\/(\d+)\/(\d+)\/(\d+)\.png$/),[z,x,y]=parts.slice(1).map(Number);
 const ok=cached.has(tileId(z,x,y))||behavior==='all-cached';
 return {ok,status:ok?200:404,headers:new Headers({'X-Scout-Tile-Exact':'true','X-Scout-Tile-Zoom':String(z),
  'X-Scout-Imagery-Source-Id':'happyman_rudy_twmap','X-Scout-Tile-Source':'local_source_cache'}),blob:async()=>new Blob(['tile'])};
};
const open=async()=>{
 opened++; let z=12,viewZoom=12,x=Math.floor(.8*2**z),y=Math.floor(.45*2**z),auto=true,matrixReadyAt=0;
 const key=()=>tileId(z,x,y),fill=()=>{if(auto&&!(behavior==='high-failure'&&z===20))cached.add(key())}; fill();
 const slow=behavior==='slow-progress'&&opened===1;
 if(slow)cached.add(tileId(z,x+1,y));
 const descriptor={renderer:'svg',doc:{location:{href:base}},projectId:()=>project,
  tileView:()=>({tileTemplate:template,tiles:[{z,x,y}],bounds:{west:lon(x+.1,z),east:lon(x+.9,z),north:lat(y+.1,z),south:lat(y+.9,z)}}),
  snapshot:()=>{const available=cached.has(key()),late=behavior==='native-receipt-late'&&z===20&&time<matrixReadyAt,
   arriving=late||(slow&&time<75000),success=late?0:slow?(time>=75000?2:time>=40000?1:0):available?1:0;
   return {activeRenderer:behavior==='renderer-fallback'?'maplibre':'svg',rendererReady:true,
   matrix:late?19:z,verified:available&&!arriving?z:null,required:slow?2:1,success,pending:arriving?(slow?2:1)-success:0,errors:available?0:1,unverified:0,
   status:arriving?'loading':available?'ready':'retained-previous',view:key(),generation:key(),matrices:[z],
   scrollTop:behavior==='scroll-offset'?52.5:0,scrollLeft:0,
   initializationReceipt:{status:'fixture-receipt',activeMaps:1},
   viewLimits:behavior==='maximum-unknown'?null:{viewZoom,maxViewZoom:behavior==='post-z20-overzoom'?23:20,
    nativePixelRatio:2**(viewZoom-20),measuredTileCount:slow?2:1,pixelScaleBasis:'svg-tile-css-rectangle'},
   tiles:[{key:key(),href:template.replace('{z}',z).replace('{x}',x).replace('{y}',y)},
    ...(slow?[{key:tileId(z,x+1,y),href:template.replace('{z}',z).replace('{x}',x+1).replace('{y}',y)}]:[])]};},
  act:async action=>{actions.push(action);
   if(action==='plus'&&behavior==='native-receipt-late'&&viewZoom===20)throw new Error('Actual + is disabled at maximum');
   if(action==='fit'){z=12;viewZoom=12;x=Math.floor(.8*2**z);y=Math.floor(.45*2**z)}
   if(action==='plus'){if(behavior==='first-plus-stuck'){x++}else{viewZoom=Math.min(behavior==='post-z20-overzoom'?23:20,viewZoom+1);z=Math.min(20,z+1);x=Math.floor(.8*2**z);y=Math.floor(.45*2**z)}}
   if(action==='plus'&&behavior==='native-receipt-late'&&z===20)matrixReadyAt=time+1200;
   if(action==='right')x++;if(action==='left')x--;if(action==='up')y--;if(action==='down')y++;
   if(action==='stop-updates'&&behavior!=='stop-ignored')auto=false;
   if(action==='start-updates'){auto=true;if(behavior==='recovery-reset')x++}
   fill();
  }};
 let done=false;return {descriptor,close(){if(!done){done=true;closed++}
  if(behavior==='final-close-throw'&&opened>=2)throw new TypeError('fixture cleanup rejected');
  return {disposed:true,activeMaps:0,pendingInitializations:0,errors:[]};}};
};
(async()=>{
const result=await api.runCase({id:'map',renderer:'svg',variant:'default',key:'map/svg/default'},{projectId:project,open});
const summary=api.summarize([result]);
ASSERTIONS
})().catch(error=>{console.error(error);process.exitCode=1});
"""


def workflow(behavior, assertions):
    node(WORKFLOW.replace("BEHAVIOR", json.dumps(behavior)).replace("ASSERTIONS", assertions))


def test_actual_stage_sequence_requires_reload_cold_miss_and_same_view_recovery():
    workflow("normal", r"""
assert.equal(summary.status,'passed');assert.equal(summary.passed,10);
assert.equal(opened,2);assert.equal(closed,2);
assert.deepEqual(result.stages.map(item=>item.stage),api.STAGES);
const miss=result.stages.find(item=>item.stage==='cache-miss').snapshot;
const recovery=result.stages.find(item=>item.stage==='recovery').snapshot;
assert.equal(miss.cacheHttpStatus,404);assert.equal(miss.failureDetected,true);
assert.equal(recovery.recoveredTile,miss.genuineCacheMiss);assert.equal(recovery.view,miss.view);
assert.ok(actions.indexOf('stop-updates')<actions.indexOf('start-updates'));
""")


def test_decoded_native_progress_extends_idle_deadline_without_allowing_incomplete_tiles():
    workflow("slow-progress", r"""
assert.equal(summary.status,'passed');assert.equal(summary.passed,10);
assert.ok(time>=75000,'Cold load must be observed beyond the original 60-second total deadline');
assert.equal(result.stages[0].snapshot.required,2);assert.equal(result.stages[0].snapshot.success,2);
assert.equal(opened,closed);
""")


def test_reaching_actual_camera_maximum_waits_for_native_receipt_before_more_plus():
    workflow("native-receipt-late", r"""
assert.equal(summary.status,'passed');assert.equal(summary.passed,10);
assert.equal(result.stages.find(item=>item.stage==='native-z20').snapshot.matrix,20);
assert.equal(result.stages.find(item=>item.stage==='actual-maximum').snapshot.viewLimits.viewZoom,20);
assert.equal(actions.filter(action=>action==='plus').length,8);
assert.equal(opened,closed);
""")


@pytest.mark.parametrize(("behavior", "failed_stage"), [
    ("first-plus-stuck", "first-plus"), ("high-failure", "native-z20"),
    ("all-cached", "cache-miss"), ("renderer-fallback", "initial"),
    ("recovery-reset", "recovery"), ("stop-ignored", "cache-miss"),
    ("scroll-offset", "initial"),
    ("post-z20-overzoom", "actual-maximum"), ("maximum-unknown", "actual-maximum"),
])
def test_replayed_regressions_never_become_passed(behavior, failed_stage):
    workflow(behavior, f"""
assert.equal(summary.status,'warning');
assert.equal(result.stages.find(item=>item.status==='warning').stage,{json.dumps(failed_stage)});
assert.equal(result.stages.length,10);assert.equal(opened,closed);
if({json.dumps(behavior)}==='first-plus-stuck')assert.equal(actions.filter(action=>action==='plus').length,1);
const failure=result.stages.find(item=>item.status==='warning');
assert.ok(failure.snapshot);assert.equal(failure.snapshot.initializationReceipt.status,'fixture-receipt');
""")


def test_cleanup_exception_is_retained_and_does_not_abort_later_cases():
    workflow("final-close-throw", r"""
assert.equal(summary.status,'warning');assert.equal(summary.passed,10);
assert.equal(summary.cleanupFailures,1);assert.equal(result.cleanupStatus,'warning');
assert.equal(result.cleanup.at(-1).receipt.errors[0].errorName,'TypeError');
const registry=['overview-map','lbs-map','permission-map','emergency-review-map','architecture-map','pace-fit-map',
 'map','weather-map','navigation-map','debug-map','permission-day-maps'].map(id=>({id}));
let updates=0;
const batch=await api.run({projectId:project,currentProjectId:()=>project,registry,dailyIds:['D1'],open,
 onProgress(item,report){assert.ok(report.plannedStages>0);assert.equal(report.activeResult,item);updates++;}});
assert.equal(batch.status,'warning');assert.equal(batch.cases.length,37);assert.ok(updates>=37);
assert.ok(batch.cases.every(item=>item.cleanupStatus==='warning'));
assert.equal(opened,closed);
""")


def test_initialization_failure_keeps_receipts_even_without_a_descriptor():
    node(BASE + r"""
(async()=>{
const initializationEvidence=[{element:'runtimeMapLibre',state:{maplibreInitReceipt:'{"reason":"ready_timeout"}'}}];
const cleanupReceipt={disposed:true,activeMaps:0,pendingInitializations:0,errors:[]};
const result=await api.runCase({key:'debug/maplibre',renderer:'maplibre'},{projectId:project,
 open:async()=>{throw Object.assign(new Error('initial load failed'),{initializationEvidence,cleanupReceipt})}});
assert.equal(result.status,'warning');assert.equal(result.stages[0].snapshot,null);
assert.deepEqual(result.stages[0].initializationEvidence,initializationEvidence);
assert.deepEqual(result.cleanup[0].receipt,cleanupReceipt);assert.equal(result.stages.length,10);
})().catch(error=>{console.error(error);process.exitCode=1});
""")


@pytest.mark.parametrize("renderer", ["maplibre", "svg"])
@pytest.mark.parametrize("scenario", ["ready", "pending-deadline", "actual-fallback"])
def test_real_dom_pending_renderer_lifecycle_preserves_native_gate_and_initial_receipt(renderer, scenario):
    program = BASE + r"""
const {JSDOM}=require('jsdom');
const renderer=RENDERER,scenario=SCENARIO;
const dom=new JSDOM('<div id="mapRendererShell" data-map-renderer-active="pending" data-map-renderer-state="loading"><div id="mapLibreEvidenceMap"></div><svg id="map" viewBox="0 0 1000 720"><g data-layer-group="rudy-twmap"></g></svg></div>',{url:base});
const doc=dom.window.document,shell=doc.querySelector('#mapRendererShell'),host=doc.querySelector('#mapLibreEvidenceMap');
const group=doc.querySelector('[data-layer-group="rudy-twmap"]');
const tile=href(12,3300,1900),root=doc.querySelector(renderer==='maplibre'?'#mapLibreEvidenceMap':'#map');
let time=0,opened=0,closed=0,previousPhase=null;const observed=[],progress=[];
const realTimeout=global.setTimeout;Date.now=()=>time;
global.setTimeout=(callback,ms)=>{if(ms<1000){time+=ms;return realTimeout(callback,0)}return realTimeout(callback,ms)};
global.createImageBitmap=async()=>({width:256,height:256,close(){}});
global.fetch=async()=>({ok:true,status:200,headers:headers({'X-Scout-Tile-Zoom':'12'}),blob:async()=>new Blob(['cached-native'])});
const descriptor=api.descriptorFor({kind:'pretrip',renderer,root,doc,projectId:()=>project,
 tileView:()=>({bounds:{west:110,east:111,north:24,south:23},tileTemplate:tile.replace('/12/3300/1900.png','/{z}/{x}/{y}.png'),tiles:[{z:12,x:3300,y:1900}]})});
const productionSnapshot=descriptor.snapshot;
descriptor.snapshot=()=>{
 const phase=scenario==='pending-deadline'||time<600?'pending':time<1200?'requested-loading':scenario==='actual-fallback'?'fallback':'ready';
 if(phase!==previousPhase){
  previousPhase=phase;
  host.dataset.maplibreInitReceipt=JSON.stringify({phase,rendererRequested:renderer,startedAt:0});
  host.dataset.maplibreRasterTransport='same-origin-protocol';
  if(phase!=='pending'){
   const complete=phase!=='requested-loading';
   Object.assign(shell.dataset,{mapRendererActive:phase==='fallback'?(renderer==='maplibre'?'svg':'maplibre'):renderer,
    mapRendererState:complete?'ready':'loading',mapRendererReason:phase==='fallback'?'fixture-renderer-fallback':'initialization'});
   Object.assign(host.dataset,{maplibreRasterNativeZoom:'12',maplibreRasterVerifiedNativeZoom:complete?'12':'',
    maplibreRasterRequiredCount:'1',maplibreRasterSuccessCount:complete?'1':'0',maplibreRasterPendingCount:complete?'0':'1',
    maplibreRasterErrorCount:'0',maplibreRasterUnverifiedCount:complete?'0':'1',maplibreRasterState:complete?'available':'loading'});
   Object.assign(group.dataset,{requestedTileZoom:'12',displayedTileZoom:complete?'12':'',tileGenerationState:complete?'ready':'loading',activeTileGenerationKey:complete?'12-cohort':''});
   group.innerHTML=`<g data-tile-generation="${complete?'active':'pending'}"><image data-raster-tile="12/3300/1900" data-tile-generation-loaded="${complete?'true':'false'}" href="${tile}"/></g>`;
  }
 }
 const snapshot=productionSnapshot();
 if(observed.at(-1)?.phase!==phase)observed.push({phase,time,snapshot:structuredClone(snapshot)});
 return snapshot;
};
(async()=>{
const result=await api.runCase({id:'map',renderer,variant:'default',key:'map/'+renderer+'/default'},{projectId:project,
 open:async()=>{opened++;if(opened>1)throw Error('fixture stops after proven initial stage');
  return {descriptor,close:async()=>{closed++;return {disposed:true,activeMaps:0,pendingInitializations:0,errors:[]}}}},
 onProgress:item=>{if(item.activeStage==='initial'&&item.liveSnapshot)progress.push(structuredClone(item.liveSnapshot));}});
const initial=result.stages.find(stage=>stage.stage==='initial');
assert.equal(observed[0].snapshot.activeRenderer,'pending');assert.equal(observed[0].snapshot.initializationReceipt.phase,'pending');
assert.ok(progress.some(snapshot=>snapshot.initializationReceipt?.phase==='pending'),'The initial receipt must be visible before initialization settles');
assert.equal(closed,1);
if(scenario==='ready'){
 assert.deepEqual(observed.map(item=>item.phase),['pending','requested-loading','ready']);
 assert.equal(observed[1].snapshot.activeRenderer,renderer);assert.equal(api.nativeComplete(observed[1].snapshot),false);
 assert.equal(initial.status,'passed');assert.equal(initial.snapshot.activeRenderer,renderer);
 assert.equal(initial.snapshot.initializationReceipt.phase,'ready');assert.equal(api.nativeComplete(initial.snapshot),true);
 assert.equal(result.stages[1].stage,'reload');assert.match(result.stages[1].detail,/fixture stops/);
}else{
 assert.equal(initial.status,'warning');assert.equal(initial.snapshotSource,'current-renderer');
 assert.equal(result.stages.filter(stage=>stage.status==='passed').length,0);
 if(scenario==='pending-deadline'){
  assert.ok(time>=60000);assert.match(initial.detail,/deadline/);assert.doesNotMatch(initial.detail,/Requested .*received/);
  assert.equal(initial.snapshot.activeRenderer,'pending');assert.equal(initial.snapshot.initializationReceipt.phase,'pending');
 }else{
  assert.ok(time>=1200&&time<60000);assert.match(initial.detail,/Requested .*received/);
  assert.equal(initial.snapshot.activeRenderer,renderer==='maplibre'?'svg':'maplibre');
  assert.equal(initial.snapshot.initializationReceipt.phase,'fallback');
 }
}
dom.window.close();
})().catch(error=>{console.error(error);process.exitCode=1});
"""
    node(program.replace("RENDERER", json.dumps(renderer)).replace("SCENARIO", json.dumps(scenario)))


@pytest.mark.parametrize("outcomes", [
    ["passed", "passed", "passed"], ["warning", "passed", "passed"],
    ["passed", "warning", "passed"], ["passed", "passed", "warning"],
])
def test_existing_037_retains_offline_and_cwa_gates_alongside_native_matrix(outcomes):
    program = r"""
const assert=require('node:assert/strict');
const NAVIGATION_RUDY_TILE_SOURCE={maxZoom:20,preparedMaxZoom:14,initialMaxZoom:13};
function updateDashboardRudyTileLayer(){} function navigationRudyBaseZoom(){}
function renderNavigationWorkspaceMap(){} function renderArchitectureMap(){}
const diagnosticPublishRudyReport=()=>{};
const diagnosticCompactSource=()=> 'NAVIGATION_RUDY_TILE_SOURCE.maxZoom NAVIGATION_RUDY_TILE_SOURCE.initialMaxZoom renderNavigationRudyTileLayer renderDashboardRudyTileLayer';
const diagnosticRequire=(value,message)=>{if(!value)throw Error(message)};
const diagnosticDynamicRudyTileContract=label=>({label,initialMatrix:12,firstMatrix:13,highMatrix:20});
const diagnosticWeatherRudyTileContract=()=>diagnosticDynamicRudyTileContract('Weather');
const diagnosticEnvelope=async()=>({data:'pretrip-source'}),projectId=()=> 'trip';
const statuses=OUTCOMES,calls=[];
const diagnosticWeatherLiveTiles=async(options={})=>{calls.push(options.native===true);return {status:statuses[options.native?1:0],detail:'tiles'}};
const diagnosticWeatherLiveFrames=async()=>({status:statuses[2],detail:'cached CWA'});
const diagnosticAvailability=(dataStatus,detail)=>({status:'passed',dataStatus,detail});
const diagnosticWarning=(detail,dataStatus)=>({status:'warning',dataStatus,detail});
FUNCTION
(async()=>{const result=await diagnosticCheck037();assert.deepEqual(calls,[false,true]);
 assert.equal(result.status,statuses.every(status=>status==='passed')?'passed':'warning');
})().catch(error=>{console.error(error);process.exitCode=1});
"""
    node(program.replace("OUTCOMES", json.dumps(outcomes)).replace("FUNCTION", function("diagnosticCheck037")))


def test_probe_boundary_uses_existing_isolation_and_does_not_change_cwa_policy():
    prepare = function("diagnosticPrepareRudyEntry")
    assert "DIAGNOSTIC_MAP_PROBE" in prepare and 'get("diagnosticNativeTiles") === "1"' in prepare
    assert "context.projectId === projectId()" in prepare
    assert "postJson(" not in prepare and "localStorage.setItem" not in prepare
    assert "initializeNavigationTerrainMapLibre" in prepare and "bindDashboardMapViewports" in prepare
    opening = function("diagnosticOpenRudyProbe")
    assert "left:-" not in opening and "opacity:0.01" in opening
    assert "diagnosticNativeTiles" not in function("diagnosticWeatherLiveFrames")
    assert 'url.searchParams.get("cache_only") === "1"' in function("diagnosticWeatherValidateTileUrls")
    weather_contract = function("diagnosticWeatherRudyTileContract")
    assert "Math.log2" not in weather_contract and "worldPixelsAtFit" not in weather_contract


@pytest.mark.parametrize("scenario", ["saved", "current", "missing", "zero", "wrong-project", "duplicate-day"])
def test_daily_discovery_reads_existing_candidate_without_visiting_permission_or_writing(scenario):
    program = r"""
const assert=require('node:assert/strict');
const scenario=SCENARIO,selectedProject='diagnostic_trip',calls=[];
const projectId=()=>selectedProject,asArray=value=>Array.isArray(value)?value:[];
const diagnosticRequire=(value,message)=>{if(!value)throw Error(message)};
const draft={proposal_profile:'ref_gpx_proposal_v1',source_sha256:'b'.repeat(64),days:
 scenario==='zero'?[]:[{day_kind:'on_trail',mission_day_id:'D1'},{day_kind:'transfer',mission_day_id:'D0'}]};
if(scenario==='duplicate-day')draft.days.push({day_kind:'on_trail',mission_day_id:'D1'});
const state={permissionBaselineDraft:scenario==='current'?draft:null,permissionBaselineCandidateRef:'candidate-1'};
const item={status:'current',source_mode:'reference_gpx',version_ref:'candidate-1',version_sha256:'a'.repeat(64)};
const fetchJson=async(url,options)=>{calls.push({url,options});return url.includes('/detail?')
 ? {project_id:scenario==='wrong-project'?'other_trip':selectedProject,writes_performed:false,status:'current',draft,
   saved_candidate:{version_ref:item.version_ref,version_sha256:item.version_sha256}}
 : {project_id:selectedProject,writes_performed:false,candidates:scenario==='missing'?[]:[item]}};
FUNCTION
(async()=>{const context=await diagnosticRudyPermissionContext(selectedProject);
 assert.equal(context.dailyEvidence.writesPerformed,false);
 assert.ok(calls.every(call=>call.options.cache==='no-store'&&call.url.includes('/'+selectedProject+'/mission-baseline/candidates')));
 if(scenario==='current'){assert.equal(calls.length,0);assert.equal(context.dailyEvidence.source,'current-ui-draft');}
 if(scenario==='saved'){assert.equal(calls.length,2);assert.equal(context.dailyEvidence.source,'saved-candidate-get');
   assert.equal(context.dailyEvidence.candidateSha256,item.version_sha256);}
 if(['saved','current'].includes(scenario)){assert.deepEqual(context.dailyIds,['D1']);assert.equal(context.dailyEvidence.onTrailDayCount,1);}
 if(scenario==='zero'){assert.deepEqual(context.dailyIds,[]);assert.equal(context.dailyEvidence.onTrailDayCount,0);
   assert.match(context.dailyEvidence.reason,/0 on-trail days.*incomplete/);}
 if(['missing','wrong-project','duplicate-day'].includes(scenario)){assert.equal(context.permissionBaselineDraft,null);
   assert.deepEqual(context.dailyIds,[]);assert.match(context.dailyEvidence.reason,/incomplete/);}
 assert.equal(state.permissionBaselineDraft,scenario==='current'?draft:null,'Discovery must not restore a candidate in user state');
})().catch(error=>{console.error(error);process.exitCode=1});
"""
    node(program.replace("SCENARIO", json.dumps(scenario)).replace("FUNCTION", function("diagnosticRudyPermissionContext")))


def test_dom_report_contains_full_failure_json_and_preserves_expanded_details():
    node(BASE + r"""
const {JSDOM}=require('jsdom');
const dom=new JSDOM('<main id="mount"></main>',{url:base});
const document=dom.window.document,projectId=()=>project,asArray=value=>Array.isArray(value)?value:[];
const escapeHtml=value=>String(value).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
""" + function("renderDiagnosticRudyResults") + r"""
const detail='missing native tile '+ 'evidence '.repeat(100)+'<img src=x onerror=alert(1)>';
const row={key:'map/maplibre/default',activeStage:'recovery',status:'warning',cleanupStatus:'passed',
 stages:[{stage:'native-z20',status:'warning',detail,snapshot:{matrix:20,verified:19,required:144,success:15,pending:129,
 initializationReceipt:{reason:'native-load-error'}}},{stage:'recovery',status:'not_checked',detail:'Blocked by native-z20'}]};
const report={projectId:project,status:'warning',plannedCases:34,plannedStages:340,stageNames:api.STAGES,cases:[row],activeResult:row};
const mount=document.querySelector('#mount');mount.innerHTML=renderDiagnosticRudyResults(report);
assert.deepEqual(JSON.parse(mount.querySelector('[data-diagnostic-rudy-json]').textContent),report);
assert.match(mount.querySelector('[data-diagnostic-rudy-first-failure]').textContent,/native-z20/);
assert.equal(mount.querySelector('img'),null);
mount.querySelector('[data-diagnostic-rudy-json-details]').open=true;
mount.querySelector('[data-diagnostic-rudy-cases-details]').open=true;
mount.querySelector('[data-diagnostic-rudy-case]').open=true;
row.liveSnapshot={matrix:20,success:15,required:144,pending:129,errors:0,status:'loading'};
mount.innerHTML=renderDiagnosticRudyResults(report,{status:'running',detail:'running'});
assert.equal(mount.querySelector('[data-diagnostic-rudy-json-details]').open,true);
assert.equal(mount.querySelector('[data-diagnostic-rudy-case]').open,true);
assert.match(mount.querySelector('[data-diagnostic-rudy-live-state]').textContent,/15\/144.*129/);
assert.equal(JSON.parse(mount.querySelector('[data-diagnostic-rudy-json]').textContent).diagnosticResult.status,'running');
assert.equal(renderDiagnosticRudyResults({...report,projectId:'other_trip'}),'');
dom.window.close();
""")


def test_progress_publisher_keeps_workspace_scope_and_snapshot_copy():
    node(BASE + r"""
const projectId=()=>project;let stored={},updates=0;
const diagnosticResult=()=>stored,diagnosticSetResult=(id,patch)=>{assert.equal(id,'DASH-037');stored={...stored,...patch}};
const updateDiagnosticDom=id=>{assert.equal(id,'DASH-037');updates++};
""" + function("diagnosticPublishRudyReport") + r"""
const report={projectId:project,status:'running',cases:[{key:'case',stages:[]}]};
diagnosticPublishRudyReport({...report,offlineProbe:{status:'passed'}},'first case');
report.cases[0].stages.push({stage:'initial',status:'warning',detail:'failure'});
assert.equal(stored.rudyNativeReport.cases[0].stages.length,0);
diagnosticPublishRudyReport(report,'failed initial');
assert.equal(stored.rudyNativeReport.cases[0].stages[0].status,'warning');
assert.equal(stored.rudyNativeReport.offlineProbe.status,'passed');
diagnosticPublishRudyReport({...report,projectId:'other_trip'});
assert.equal(updates,2);assert.equal(stored.detail,'failed initial');
""")


def test_outer_dispose_awaits_canonical_cleanup_and_marks_missing_receipt():
    node(BASE + r"""
const {JSDOM}=require('jsdom');
const dom=new JSDOM('<iframe src="/admin/pretrip"></iframe>',{url:base});
const document=dom.window.document,location=dom.window.location,asArray=value=>Array.isArray(value)?value:[];
const navigationTerrainMapLibreRuntime={maps:[],pendingInitializations:new Set(),initializationStarted:0,initializationSettled:0};
const stopNavigationTerrainPolling=()=>{},destroyNavigationTerrainMapLibre=()=>{};
""" + function("diagnosticMapCleanupComplete") + function("diagnosticDisposeNavigationMaps") + function("diagnosticDisposeRudyProbe") + r"""
(async()=>{
let disposed=false;
document.querySelector('iframe').contentWindow.scoutPretripMapRendererBridge={dispose:async()=>{
 await Promise.resolve();disposed=true;return {disposed:true,activeMaps:0,pendingInitializations:0,errors:[]};}};
const good=await diagnosticDisposeRudyProbe();assert.equal(disposed,true);assert.equal(good.disposed,true);
delete document.querySelector('iframe').contentWindow.scoutPretripMapRendererBridge;
const missing=await diagnosticDisposeRudyProbe();assert.equal(missing.disposed,false);
assert.equal(missing.activeMaps,null);assert.equal(missing.errors[0].errorName,'MissingCanonicalDispose');
dom.window.close();
})().catch(error=>{console.error(error);process.exitCode=1});
""")


@pytest.mark.parametrize("missing_hook", [False, True])
def test_outer_dispose_cancels_actual_shared_svg_generation_and_ignores_late_callbacks(missing_hook):
    program = BASE + r"""
const {JSDOM}=require('jsdom');
const dom=new JSDOM('<div id="daily" data-dashboard-map-viewport="daily"><svg><g data-dashboard-rudy-tile-layer="true"></g></svg></div>',{url:base});
var window=dom.window;
const document=window.document,location=window.location,asArray=value=>Array.isArray(value)?value:[];
const viewport=document.querySelector('#daily'),layer=viewport.querySelector('g');
const navigationTerrainMapLibreRuntime={maps:[],pendingInitializations:new Set(),initializationStarted:0,initializationSettled:0},DASHBOARD_RUDY_TILE_SWAP_TIMEOUT_MS=12000;
const stopNavigationTerrainPolling=()=>{},destroyNavigationTerrainMapLibre=()=>{};
const timers=new Map();let timerId=0,published=0;
window.setTimeout=callback=>{const id=++timerId;timers.set(id,callback);return id};window.clearTimeout=id=>timers.delete(id);
const enforceDashboardMapRenderPolicy=()=>{};
const publishDashboardRudyTileState=(target,values)=>{published++;for(const [name,value] of Object.entries(values))target.dataset['dashboardTile'+name]=String(value)};
""" + function("discardDashboardPendingRudyTileGeneration") + function("stageDashboardRudyTileGeneration") + function("diagnosticMapCleanupComplete") + function("diagnosticDisposeNavigationMaps") + function("diagnosticDisposeRudyProbe") + r"""
(async()=>{
const markup=`<image data-dashboard-rudy-tile="20/850000/450000" href="${href()}"/><image data-dashboard-rudy-tile="20/850001/450000" href="${href(20,850001,450000)}"/>`;
assert.equal(stageDashboardRudyTileGeneration(viewport,layer,markup,'pending-fixture',20,{zoom:256}),true);
const generation=layer.querySelector('[data-dashboard-rudy-tile-generation="pending"]'),images=[...generation.querySelectorAll('image')];
const queuedCallbacks=[...timers.values()],publishedBefore=published;
assert.equal(timers.size,1);assert.equal(typeof generation.cancelRudyGeneration,'function');
if(MISSING_HOOK)delete generation.cancelRudyGeneration;
const receipt=await diagnosticDisposeRudyProbe();
assert.equal(viewport.isConnected,false);assert.equal(layer.dataset.dashboardRudyPendingTileKey,undefined);
assert.equal(layer.querySelector('[data-dashboard-rudy-tile-generation="pending"]'),null);
assert.ok(images.every(image=>!image.hasAttribute('href')));
assert.equal(receipt.svg[0].pendingBefore,1);assert.equal(receipt.svg[0].pendingAfter,0);
if(MISSING_HOOK){
 assert.equal(receipt.disposed,false);assert.equal(receipt.activeMaps,null);
 assert.ok(receipt.errors.some(error=>error.errorName==='MissingCancellationHook'));
 assert.equal(timers.size,1,'Missing cancellation is unverified cleanup and must never be certified');
 timers.clear();
}else{
 assert.equal(receipt.disposed,true);assert.equal(receipt.activeMaps,0);assert.equal(receipt.pendingInitializations,0);
 assert.equal(timers.size,0);
 const dataBefore=JSON.stringify({...viewport.dataset});
 images.forEach(image=>{image.dispatchEvent(new window.Event('load'));image.dispatchEvent(new window.Event('error'))});
 queuedCallbacks.forEach(callback=>callback());
 assert.equal(timers.size,0);assert.equal(published,publishedBefore);
 assert.equal(JSON.stringify({...viewport.dataset}),dataBefore,'Cancelled callbacks must not promote or mutate the disposed view');
 assert.equal(layer.querySelector('[data-dashboard-rudy-tile-generation="active"]'),null);
}
dom.window.close();
})().catch(error=>{console.error(error);process.exitCode=1});
"""
    node(program.replace("MISSING_HOOK", json.dumps(missing_hook)))


def test_outer_dispose_detects_live_navigation_transport_and_still_cleans_svg():
    node(BASE + r"""
const {JSDOM}=require('jsdom');
const dom=new JSDOM('<canvas id="nav"></canvas><div id="svg" data-dashboard-map-viewport="svg"></div>',{url:base});
const document=dom.window.document,location=dom.window.location,asArray=value=>Array.isArray(value)?value:[];
const canvas=document.querySelector('#nav'),viewport=document.querySelector('#svg');
const transport={destroyed:false,controllers:new Map([['inflight',{}]])};
const navigationTerrainMapLibreRuntime={maps:[{map:{getCanvas:()=>canvas},rudyTransport:transport}],pendingInitializations:new Set(),initializationStarted:0,initializationSettled:0};
const stopNavigationTerrainPolling=()=>{};
const destroyNavigationTerrainMapLibre=()=>{for(const entry of navigationTerrainMapLibreRuntime.maps)entry.mapDisposeReceipt={disposed:true,mapRemoved:true,errors:[]};navigationTerrainMapLibreRuntime.maps=[];canvas.remove()};
""" + function("diagnosticMapCleanupComplete") + function("diagnosticDisposeNavigationMaps") + function("diagnosticDisposeRudyProbe") + r"""
(async()=>{
const receipt=await diagnosticDisposeRudyProbe();
assert.equal(receipt.disposed,false);assert.equal(receipt.activeMaps,null);assert.equal(viewport.isConnected,false);
assert.ok(receipt.errors.some(error=>error.errorName==='ActiveTileTransportRemains'));
dom.window.close();
})().catch(error=>{console.error(error);process.exitCode=1});
""")


def test_open_failure_captures_initialization_evidence_and_always_removes_frame():
    node(BASE + r"""
const {JSDOM}=require('jsdom');
const dom=new JSDOM('<body></body>',{url:base});
const document=dom.window.document,location=dom.window.location,projectId=()=>project;
const diagnosticRequire=(value,message)=>{if(!value)throw Error(message)};
var window={ScoutRudyLiveDiagnostic:api};let disposed=0;
const diagnosticWaitForMapOrder=async(read)=>{
 const frame=document.querySelector('iframe');
 frame.contentDocument.open();frame.contentDocument.write('<html data-diagnostic-map-probe-ready="true"><body><div id="workspace"><div id="host" data-maplibre-init-receipt="receipt-evidence"></div></div></body></html>');frame.contentDocument.close();
 const bridge={prepare:async()=>{throw new Error('ready_timeout')},dispose:async()=>{disposed++;throw new TypeError('cleanup rejected')}};
 frame.contentWindow.scoutDashboardRudyProbe=bridge;return read();
};
""" + function("diagnosticRudyFrameDocument") + function("diagnosticRudyInitializationEvidence") + function("diagnosticOpenRudyProbe") + r"""
(async()=>{
await assert.rejects(diagnosticOpenRudyProbe({key:'map/maplibre/default',renderer:'maplibre'},{projectId:project}),error=>{
 assert.equal(error.message,'ready_timeout');assert.equal(error.initializationEvidence[0].state.maplibreInitReceipt,'receipt-evidence');
 assert.equal(error.cleanupReceipt.disposed,false);return true;
});
assert.equal(disposed,1);assert.equal(document.querySelector('iframe'),null);dom.window.close();
})().catch(error=>{console.error(error);process.exitCode=1});
""")


def test_open_waits_through_real_dom_null_document_element_before_preparing():
    node(BASE + r"""
const {JSDOM}=require('jsdom');
const dom=new JSDOM('<body></body>',{url:base});
const document=dom.window.document,location=dom.window.location,projectId=()=>project;
const diagnosticRequire=(value,message)=>{if(!value)throw Error(message)};
var window={ScoutRudyLiveDiagnostic:api};let prepared=0,disposed=0,emptyDocuments=0;
const diagnosticWaitForMapOrder=async(read)=>{
 const frame=document.querySelector('iframe'),doc=frame.contentDocument;
 doc.documentElement?.remove();assert.equal(doc.documentElement,null);
 assert.equal(read(),null,'A document without its root must remain pending, not throw on dataset');emptyDocuments++;
 doc.open();doc.write('<html data-diagnostic-map-probe-ready="true"><body><div id="workspace"><div id="maproot" data-dashboard-map-viewport="map"></div></div></body></html>');doc.close();
 const root=doc.querySelector('#maproot');root.dashboardMapController={getState:()=>({zoom:1})};
 frame.contentWindow.scoutDashboardRudyProbe={prepare:async()=>{prepared++;return {kind:'dashboard-svg',renderer:'svg',root,doc,projectId}},
  dispose:async()=>{disposed++;return {disposed:true,activeMaps:0,pendingInitializations:0,errors:[]}}};
 return read();
};
""" + function("diagnosticRudyFrameDocument") + function("diagnosticRudyInitializationEvidence") + function("diagnosticOpenRudyProbe") + r"""
(async()=>{
const opened=await diagnosticOpenRudyProbe({key:'map/svg/default',renderer:'svg'},{projectId:project});
assert.equal(prepared,1);assert.equal(emptyDocuments,1);assert.equal(opened.descriptor.root.id,'maproot');
assert.equal(opened.descriptor.root.ownerDocument,opened.descriptor.doc);
assert.equal((await opened.close()).disposed,true);assert.equal(disposed,1);assert.equal(document.querySelector('iframe'),null);
dom.window.close();
})().catch(error=>{console.error(error);process.exitCode=1});
""")


def test_canonical_ready_rejects_previous_document_wrong_workspace_and_missing_map_root():
    node(BASE + r"""
const {JSDOM}=require('jsdom');
const dom=new JSDOM('<iframe></iframe>',{url:base});
const document=dom.window.document,location=dom.window.location,frame=document.querySelector('iframe');
""" + function("diagnosticRudyFrameDocument") + r"""
const expected=new URL('/admin/pretrip?projectId='+project+'&diagnosticMapProbe=1&diagnosticNativeTiles=1&mapRenderer=maplibre',base).href;
const write=(html)=>{const doc=frame.contentDocument;doc.open();doc.write(html);doc.close();return doc};
frame.src=expected;
const previousDocument=write('<body><div id="mapLibreEvidenceMap"></div></body>');
frame.contentWindow.scoutPretripMapRendererBridge={generation:'old'};
const options={previousDocument,rootSelector:'#mapLibreEvidenceMap',bridgeName:'scoutPretripMapRendererBridge'};
assert.equal(diagnosticRudyFrameDocument(frame,expected,options),null,'Same URL with the previous page bridge is still stale');
frame.src=expected.replace(project,'different_project');
write('<body><div id="mapLibreEvidenceMap"></div></body>');frame.contentWindow.scoutPretripMapRendererBridge={generation:'wrong'};
assert.equal(diagnosticRudyFrameDocument(frame,expected,options),null);
frame.src=expected;
let current=write('<body></body>');const bridge={generation:'current'};frame.contentWindow.scoutPretripMapRendererBridge=bridge;
assert.equal(diagnosticRudyFrameDocument(frame,expected,options),null,'Bridge existence alone cannot prove the actual map root exists');
current.documentElement.remove();assert.equal(diagnosticRudyFrameDocument(frame,expected,options),null);
current=write('<body><div id="mapLibreEvidenceMap"></div></body>');
const ready=diagnosticRudyFrameDocument(frame,expected,options);
assert.ok(ready);assert.equal(ready.bridge,bridge);assert.equal(ready.doc,current);assert.notEqual(ready.doc,previousDocument);
assert.equal(ready.root,current.querySelector('#mapLibreEvidenceMap'));
dom.window.close();
""")
