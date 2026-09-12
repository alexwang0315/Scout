"""D038 replays production render/control wiring; fixtures are not live WebGL proof."""

import json
import re
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "docs/admin/scout-dashboard-v0.1.html"


def _functions(*names: str) -> str:
    source = PAGE.read_text()
    selected = []
    for name in names:
        match = re.search(rf"(?ms)^    (?:async )?function {name}\(.*?^    }}", source)
        assert match, name
        selected.append(match.group())
    return "\n".join(selected)


def _node(program: str) -> dict:
    result = subprocess.run(["node"], input="(function () {\n" + program + "\n})();", text=True, capture_output=True, cwd=ROOT, timeout=30)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _validation() -> str:
    return r'''
const location = new URL('http://scout.test/admin/dashboard?projectId=project-a');
const diagnosticRequire = (value, message) => {if (!value) throw Error(message);};
const camera = mode => ({center: mode==='2d'?[121,23]:[121.01,23.01],zoom:mode==='2d'?13:16,pitch:mode==='2d'?0:58,bearing:mode==='2d'?0:-28});
const renderer = mode => ({mode,domain:'observed',lens:'structure',status:'ready',styleReady:true,moving:false,camera:camera(mode),
 terrain:{source:'scout-terrain-dem'},terrainElevationStatus:'decoded',terrainCenterElevation:2000,
 sources:[{id:'scout-rudy-tw',type:'raster'},{id:'scout-terrain-dem',type:'raster-dem'},
  {id:'scout-known-gpx-reference',type:'geojson',featureCount:2}],
 rasterSources:[{id:'scout-rudy-tw',requestTemplates:['/admin/tiles/imagery/project-a/{z}/{x}/{y}?cache_only=1&exact=1']}]});
const evidence={projectId:'project-a',route:'outdoor-navigation',viewMode:'split',domain:'observed',lens:'structure',pendingInitializations:0,
 hosts:['2d','3d'].map((mode,index)=>({mode,connected:true,display:'block',visibility:'visible',hiddenAncestor:false,
  bounds:{x:index*520,y:0,width:500,height:400}})),renderers:[renderer('2d'),renderer('3d')]};
''' + _functions("diagnosticValidateNavigationCameraPage")


@pytest.mark.parametrize("mutation,expected", [
    ("evidence.hosts.pop(); evidence.renderers.pop();", "missing, duplicate"),
    ("evidence.renderers[1].status='failed';", "not a ready"),
    ("evidence.renderers[1].moving=true;", "not a ready"),
    ("evidence.renderers[1].terrainElevationStatus='verifying';", "decoded terrain"),
    ("evidence.renderers[1].terrainCenterElevation=0;", "decoded terrain"),
    ("evidence.renderers[0].sources.shift();", "Rudy source"),
    ("evidence.renderers[1].domain='prior';", "different evidence domain"),
    ("evidence.renderers[1].lens='risk';", "different evidence domain"),
    ("evidence.renderers[0].rasterSources[0].requestTemplates=['/admin/tiles/imagery/project-a/20/1/2?native=1&exact=1'];", "cache-only permission"),
    ("evidence.renderers[0].rasterSources[0].requestTemplates=['/admin/tiles/imagery/other/20/1/2?cache_only=1&exact=1'];", "another workspace"),
    ("evidence.renderers[0].rasterSources[0].requestTemplates=null;", "transport mapping"),
    ("evidence.renderers[1].camera.zoom=13;", "camera was changed"),
    ("evidence.pendingInitializations=1;", "still pending"),
    ("evidence.renderers[0].sourceInspectionError='Error';", "not a ready"),
    ("evidence.hosts[1].hiddenAncestor=true;", "hidden or has no"),
    ("evidence.hosts[1].bounds.width=0;", "hidden or has no"),
    ("evidence.hosts[1].bounds={...evidence.hosts[0].bounds};", "panes overlap"),
])
def test_page_evidence_rejects_missing_stale_unsafe_or_shared_camera(mutation: str, expected: str) -> None:
    result = _node(_validation() + mutation + r'''
let failure=null;
try {diagnosticValidateNavigationCameraPage(evidence,{viewMode:'split',domain:'observed'},{'2d':camera('2d'),'3d':camera('3d')});}
catch(error){failure=error.message;}
console.log(JSON.stringify({failure}));
''')
    assert expected in result["failure"]


def test_terrain_and_prior_keep_actual_gpx_sources_without_false_failure() -> None:
    result = _node(_validation() + r'''
const results=[];
for(const domain of ['observed','terrain','prior']) {
 evidence.domain=domain;
 for(const entry of evidence.renderers){entry.domain=domain;if(domain!=='observed') entry.sources=entry.sources.filter(source=>source.id!=='scout-rudy-tw');}
 diagnosticValidateNavigationCameraPage(evidence,{viewMode:'split',domain},{'2d':camera('2d'),'3d':camera('3d')});
 results.push({domain,gpx:evidence.renderers.map(entry=>entry.sources.find(source=>source.id==='scout-known-gpx-reference').featureCount)});
}
console.log(JSON.stringify({results}));
''')
    assert len(result["results"]) == 3
    assert all(item["gpx"] == [2, 2] for item in result["results"])


def test_pane_evidence_reads_real_dom_visibility_and_ancestor_hiding() -> None:
    program = r'''
const {JSDOM}=require('jsdom');
const dom=new JSDOM('<div id="ancestor"><div id="pane" data-navigation-maplibre-map="3d" style="display:block;visibility:visible"></div></div>');
const window=dom.window,document=window.document,Element=window.Element,getComputedStyle=window.getComputedStyle;
const pane=document.getElementById('pane'),ancestor=document.getElementById('ancestor');
pane.getBoundingClientRect=()=>({x:510,y:12,width:500,height:400});
'''
    program += _functions("diagnosticNavigationCameraPaneEvidence")
    program += r'''
const visible=diagnosticNavigationCameraPaneEvidence(pane);
ancestor.hidden=true;const hidden=diagnosticNavigationCameraPaneEvidence(pane);
ancestor.hidden=false;ancestor.style.display='none';const displayNone=diagnosticNavigationCameraPaneEvidence(pane);
ancestor.style.display='block';pane.style.visibility='hidden';const invisible=diagnosticNavigationCameraPaneEvidence(pane);
console.log(JSON.stringify({visible,hidden,displayNone,invisible}));
'''
    result = _node(program)
    assert result["visible"]["hiddenAncestor"] is False
    assert result["visible"]["bounds"] == {"x": 510, "y": 12, "width": 500, "height": 400}
    assert all(result[key]["hiddenAncestor"] for key in ["hidden", "displayNone", "invisible"])


def _workflow(options: dict) -> dict:
    program = r'''
const {JSDOM}=require('jsdom');
const dom=new JSDOM('<body><div id="workspace" tabindex="0"></div><div id="dashboardEvidence"></div><div id="dashboardMap"></div><div id="dashboardAgent"></div></body>',
 {url:'http://scout.test/admin/dashboard?projectId=project-a&diagnosticMapProbe=1&diagnosticNavigationCameraPage=1'});
const window=dom.window,document=window.document,location=window.location,Event=window.Event,KeyboardEvent=window.KeyboardEvent;
const Element=window.Element,getComputedStyle=window.getComputedStyle;
const requestAnimationFrame=fn=>queueMicrotask(fn);window.requestAnimationFrame=requestAnimationFrame;
const options=OPTIONS,DIAGNOSTIC_MAP_PROBE=true;
const state={route:'home',navigationTerrainLens:'structure',navigationTerrainViewMode:'map',navigationTerrainEvidenceDomain:'observed',
 navigationTerrainInspectorExpanded:false,navigationTerrainVerticalExaggeration:1,selected:'a',navigationTerrainData:null,
 navigationTerrainHypothesisId:'',navigationTerrainHypothesisBand:'top_10_percent_corridor'};
const navigationCameraPageProbeState={active:false,report:null};
const navigationTerrainMapLibreRuntime={maps:[],pendingInitializations:new Set(),initializationStarted:0,initializationSettled:0,cameraByMode:{}};
const projectId=()=> 'project-a',apiBase=()=>'',navigationTerrainEvidenceDomain=()=>state.navigationTerrainEvidenceDomain;
const asArray=value=>Array.isArray(value)?value:[],cssEscape=value=>value;
const diagnosticRequire=(value,message)=>{if(!value)throw Error(message);};
const loadCalls=[],loadDataScope=async scope=>{loadCalls.push(scope);if(scope==='navigation_terrain')state.navigationTerrainData=payload;},stopNavigationTerrainPolling=()=>{};
const hypothesis={selection_id:'hypothesis-a',provenance:{cache_key:'hypothesis-sha'},corridor:{overlays:[
 {mode:'top_10_percent_corridor',default_visible:true,sha256:'overlay-sha',runtime_href:'/admin/pretrip/projects/project-a/terrain-route-overlays/hypothesis-a.png'}]}};
const payload={project_id:options.wrongProject?'other':'project-a',projection_compilation:{input_fingerprint:'projection-sha'},
 terrain_raster_dem:{source_fingerprint:'dem-sha'},terrain_route_hypothesis:{selection:{default_id:'hypothesis-a',options:[hypothesis]}}};
const navigationTerrainSnapshot=()=>state.navigationTerrainData||{project_id:'project-a'};
const navigationTerrainRouteHypothesisOptions=snapshot=>snapshot?.terrain_route_hypothesis?.selection?.options||[];
const navigationTerrainRouteHypothesisSelectionId=snapshot=>{
 const choices=navigationTerrainRouteHypothesisOptions(snapshot);
 return choices.find(option=>option.selection_id===state.navigationTerrainHypothesisId)?.selection_id||snapshot?.terrain_route_hypothesis?.selection?.default_id||'';
};
const navigationTerrainRouteHypothesisOverlay=(snapshot,band)=>navigationTerrainRouteHypothesisOptions(snapshot)
 .find(option=>option.selection_id===navigationTerrainRouteHypothesisSelectionId(snapshot))?.corridor.overlays.find(overlay=>overlay.mode===band)||null;
const navigationTerrainRouteHypothesisBand=snapshot=>navigationTerrainRouteHypothesisOverlay(snapshot,state.navigationTerrainHypothesisBand)
 ?state.navigationTerrainHypothesisBand:navigationTerrainRouteHypothesisOptions(snapshot)[0]?.corridor.overlays[0]?.mode||'';
const navigationTerrainRouteHypothesisImageSource=(snapshot,band)=>{
 const overlay=navigationTerrainRouteHypothesisOverlay(snapshot,band);return overlay?{type:'image',url:overlay.runtime_href+'?v='+overlay.sha256}:null;
};
const renderTruthStrip=()=>{},hideDashboardMapHint=()=>{},routeUsesFullFrame=()=>true,routeUsesWideFrame=()=>false,evidenceDrawerCollapsed=()=>false;
const renderEvidenceDrawer=()=>'',bindRenderedControls=()=>bindNavigationTerrainControls();
const setNavigationTerrainSelection=(_lens,value)=>{state.selected=value;return true;};
const focusNavigationTerrainSelection=()=>{
 if(options.candidateMoves) for(const entry of navigationTerrainMapLibreRuntime.maps) entry.map.jumpTo({center:[121.2,23.2],zoom:entry.mode==='2d'?15:16});
};
const buttons=(attribute,values)=>values.map(value=>`<button ${attribute}="${value}">${value}</button>`).join('');
const renderOutdoorPage=()=>{
 const modes=state.navigationTerrainViewMode==='split'?['2d','3d']:[state.navigationTerrainViewMode==='terrain'?'3d':'2d'];
 return `<section data-navigation-terrain-intelligence="true">
 ${buttons('data-navigation-terrain-view',['map','terrain','split'])}
 ${buttons('data-navigation-terrain-evidence-domain',['observed','terrain','prior'])}
 ${buttons('data-navigation-terrain-lens',['structure','pressure','risk','retreat','events'])}
 ${buttons('data-navigation-terrain-vertical-exaggeration',[1,1.5,2])}
 <button data-navigation-terrain-inspector-toggle="true">Evidence</button><div data-navigation-primary-stage></div><aside data-navigation-context-inspector></aside>
 <select data-navigation-candidate-select="true" data-navigation-selection-lens="structure">
 ${['a',...(options.noCandidate?[]:['b'])].map(value=>`<option ${state.selected===value?'selected':''} value="${value}">${value}</option>`).join('')}</select>
 ${modes.filter(mode=>!(options.missingSplit&&modes.length===2&&mode==='3d')).map(mode=>`<section>
 <div data-navigation-maplibre-map="${mode}" data-navigation-evidence-domain="${state.navigationTerrainEvidenceDomain}"
 data-navigation-terrain-lens="${state.navigationTerrainLens}" data-navigation-maplibre-status="pending">
 <canvas tabindex="0"></canvas><button class="maplibregl-ctrl-zoom-in">+</button></div><button data-navigation-maplibre-fit="${mode}">Fit</button></section>`).join('')}
 </section>`;
};
const defaultCamera=mode=>({center:mode==='2d'?[121,23]:[121.01,23.01],zoom:mode==='2d'?12:15,pitch:mode==='2d'?0:58,bearing:mode==='2d'?0:-28});
const copy=value=>JSON.parse(JSON.stringify(value));
const destroyNavigationTerrainMapLibre=()=>{for(const entry of navigationTerrainMapLibreRuntime.maps){
 navigationTerrainMapLibreRuntime.cameraByMode[entry.mode]=copy(entry.map.camera);
}navigationTerrainMapLibreRuntime.maps=[];};
const navigationTerrainMapLibreCameraSnapshot=map=>copy(map.camera);
function initializeNavigationTerrainMapLibre(){
 const runtime=navigationTerrainMapLibreRuntime;runtime.initializationStarted++;
 for(const host of document.querySelectorAll('[data-navigation-maplibre-map]')){
  const mode=host.dataset.navigationMaplibreMap;
  host.getBoundingClientRect=()=>({x:mode==='2d'?0:520,y:0,width:500,height:400});
  const rudy=state.navigationTerrainEvidenceDomain==='observed';
  const style={sources:{'scout-terrain-dem':{type:'raster-dem'},'scout-known-gpx-reference':{type:'geojson',data:{features:[{geometry:{type:'LineString'}}]}}},layers:[]};
  style.sources['scout-terrain-route-corridor-top-10']=navigationTerrainRouteHypothesisImageSource(payload,'top_10_percent_corridor');
  if(rudy)style.sources['scout-rudy-tw']={type:'raster'};
  const map={camera:copy(runtime.cameraByMode[mode]||defaultCamera(mode)),getStyle:()=>style,isStyleLoaded:()=>true,isMoving:()=>false,
   getTerrain:()=>mode==='3d'?{source:'scout-terrain-dem',exaggeration:state.navigationTerrainVerticalExaggeration}:null,
   getCenter(){return {lng:this.camera.center[0],lat:this.camera.center[1]};},getZoom(){return this.camera.zoom;},getMaxZoom:()=>19,
   getCanvas:()=>host.querySelector('canvas'),resize:()=>{},jumpTo(value){Object.assign(this.camera,value);}};
  if(options.restoreReset&&runtime.initializationStarted>2)map.camera=defaultCamera(mode);
  host.dataset.navigationMaplibreStatus=options.failed3d&&mode==='3d'?'degraded':'ready';
  host.dataset.navigationTerrainElevationStatus='decoded';host.dataset.navigationTerrainCenterElevation='2000';
  const entry={mode,host,map};runtime.maps.push(entry);
  host.querySelector('button').onclick=()=>{map.camera.zoom++;if(options.crossModeZoom)for(const other of runtime.maps)if(other!==entry)other.map.camera.zoom++;};
  map.getCanvas().onkeydown=event=>{if(event.key==='ArrowRight')map.camera.center[0]+=.001;};
  host.parentElement.querySelector('[data-navigation-maplibre-fit]').onclick=()=>{map.camera=defaultCamera(mode);};
 }
 runtime.initializationSettled++;return Promise.resolve();
}
window.ScoutMapLibreEvidence={inspectRasterRenderPolicySources:(map)=>({sources:Object.entries(map.getStyle().sources)
 .filter(([id,source])=>id==='scout-rudy-tw'||source?.type==='image').map(([id,source])=>({id,type:source.type,url:source.url,
 requestTemplates:source.type==='raster'?['/admin/tiles/imagery/project-a/{z}/{x}/{y}?cache_only=1&exact=1']:null}))})};
const diagnosticWaitForMapOrder=async read=>{for(let i=0;i<30;i++){const value=read();if(value)return value;await Promise.resolve();}throw Error('fixture readiness timeout');};
const diagnosticMapCleanupComplete=receipt=>receipt?.disposed===true&&receipt.activeMaps===0&&receipt.pendingInitializations===0&&receipt.errors.length===0;
const diagnosticDisposeNavigationMaps=async()=>{destroyNavigationTerrainMapLibre();if(options.cleanupThrows)throw Error('cleanup failed');
 return {disposed:!options.cleanupFails,activeMaps:0,pendingInitializations:0,errors:options.cleanupFails?[{errorName:'FixtureCleanupFailure'}]:[]};};
'''.replace("OPTIONS", json.dumps(options))
    program += _functions("render", "bindNavigationTerrainControls", "diagnosticNavigationScopeKey",
                          "diagnosticNavigationCameraApiSource", "diagnosticNavigationCameraSourceIdentity", "diagnosticNavigationCameraSourceContext",
                          "diagnosticNavigationCameraResolveSource", "diagnosticNavigationCameraVerifySource",
                          "diagnosticNavigationCameraPaneEvidence", "diagnosticNavigationCameraPageEvidence",
                          "diagnosticValidateNavigationCameraPage", "diagnosticDisposeNavigationCameraPage",
                          "diagnosticProbeNavigationCameraPage")
    program += r'''
(async()=>{
 const before=document.getElementById('workspace').innerHTML;render();
 const diagnosticGuardHeld=document.getElementById('workspace').innerHTML===before;
 const report=await diagnosticProbeNavigationCameraPage(diagnosticNavigationCameraSourceContext());
 console.log(JSON.stringify({report,loadCalls,diagnosticGuardHeld,active:navigationCameraPageProbeState.active,
  maps:navigationTerrainMapLibreRuntime.maps.length,remainingHosts:document.querySelectorAll('[data-navigation-maplibre-map]').length}));
})().catch(error=>{console.error(error);process.exit(1);});
'''
    return _node(program)


def test_production_render_and_control_wiring_replay_covers_all_twenty_six_phases() -> None:
    result = _workflow({})
    report = result["report"]
    assert report["status"] == "passed", report
    assert len(report["phases"]) == 26
    assert all(item["status"] == "passed" for item in report["phases"])
    assert result["loadCalls"] == ["project", "navigation_terrain", "qgis_spatial"]
    assert result["diagnosticGuardHeld"] is True
    assert result["active"] is False and result["maps"] == result["remainingHosts"] == 0
    assert report["nativeTileCompletenessVerified"] is False
    assert report["phases"][2]["evidence"]["initializationStarted"] == 3


@pytest.mark.parametrize("options,phase", [
    ({"missingSplit": True}, "observed-split"),
    ({"failed3d": True}, "observed-3d-seed"),
    ({"restoreReset": True}, "observed-split"),
    ({"crossModeZoom": True}, "split-2d-plus"),
])
def test_actual_bound_transitions_preserve_renderer_and_camera_failures(options: dict, phase: str) -> None:
    result = _workflow(options)
    assert result["report"]["status"] == "failed"
    failed = next(item for item in result["report"]["phases"] if item["phase"] == phase)
    assert failed["status"] == "failed"
    assert "before" in failed and "evidence" in failed
    assert result["active"] is False and result["maps"] == 0


def test_candidate_focus_conflict_stays_failed_and_later_phases_still_run() -> None:
    report = _workflow({"candidateMoves": True})["report"]
    rows = {row["phase"]: row for row in report["phases"]}
    assert report["status"] == rows["candidate-selection"]["status"] == "failed"
    assert "camera was changed" in rows["candidate-selection"]["detail"]
    assert "followingPhaseBaseline" in rows["candidate-selection"]
    for phase in ["evidence-open", "evidence-close", "exaggeration-1.5", "fit-2d-only", "reset-3d-only"]:
        assert rows[phase]["status"] == "passed", rows[phase]


def test_missing_candidate_is_not_verified_and_never_a_success() -> None:
    report = _workflow({"noCandidate": True})["report"]
    assert report["status"] == "failed"
    assert next(row for row in report["phases"] if row["phase"] == "candidate-selection")["status"] == "not_verified"


@pytest.mark.parametrize("options", [{"cleanupFails": True}, {"cleanupThrows": True}])
def test_cleanup_failure_retains_all_phase_evidence_and_never_passes(options: dict) -> None:
    result = _workflow(options)
    assert result["report"]["status"] == "failed"
    assert len(result["report"]["phases"]) == 26
    assert all(row["status"] == "passed" for row in result["report"]["phases"])
    assert result["report"]["cleanup"]["disposed"] is False
    assert result["active"] is False


def test_page_payload_cannot_switch_projects_or_leave_probe_enabled() -> None:
    report = _workflow({"wrongProject": True})["report"]
    assert report["status"] == "failed"
    assert "another workspace" in report["preparationFailure"]["detail"]
    assert all(row["status"] == "not_run" for row in report["phases"])


@pytest.mark.parametrize("helper_status,page_status", [("passed", "failed"), ("failed", "passed"), ("passed", "warning")])
def test_helper_cannot_overwrite_page_failure_or_unverified_cleanup(helper_status: str, page_status: str) -> None:
    program = "const diagnosticNavigationCameraHelperContract=async()=>{" + (
        "return 'helper replay';" if helper_status == "passed" else "throw Error('helper failure');"
    ) + "};\n"
    program += "const diagnosticNavigationCameraWholePage=async()=>" + json.dumps({
        "status": page_status, "detail": "whole page receipt", "phases": [{"phase": "observed-split", "status": page_status}]
    }).join(["(", ");\n"])
    program += _functions("diagnosticCheck038") + "\ndiagnosticCheck038().then(result=>console.log(JSON.stringify(result)));"
    result = _node(program)
    assert result["status"] == "failed"
    assert result["cameraHelper"]["status"] == helper_status
    assert result["cameraPage"]["status"] == page_status


def test_dedicated_iframe_flag_and_readonly_guard_remain_explicit() -> None:
    html = PAGE.read_text()
    page_probe = _functions("diagnosticProbeNavigationCameraPage", "diagnosticNavigationCameraWholePage")
    assert 'diagnosticNavigationCameraPage: "1"' in page_probe
    assert '!flags.has("diagnosticNativeTiles")' in page_probe
    assert 'postJson(' not in page_probe
    assert 'if (DIAGNOSTIC_MAP_PROBE) throw new Error("Map order diagnostics are read-only.");' in html
    assert 'if (DIAGNOSTIC_MAP_PROBE && !navigationCameraPageProbeState.active) return;' in _functions("render")


def test_outer_identity_failure_retains_partial_page_phases_and_cleanup() -> None:
    program = r'''
const diagnosticNavigationCameraHelperContract=async()=> 'helper';
const diagnosticNavigationCameraWholePage=async()=>{
 const error=Error('D038 workspace or iframe document changed during verification.');
 error.cameraPageReceipt={status:'passed',projectId:'project-a',phases:[{phase:'observed-split',status:'failed',evidence:{viewMode:'split'}}]};
 error.cleanupReceipt={disposed:false,activeMaps:null,pendingInitializations:null,errors:[{errorName:'FrameRemainsConnected'}]};
 throw error;
};
'''
    program += _functions("diagnosticCheck038") + "\ndiagnosticCheck038().then(result=>console.log(JSON.stringify(result)));"
    result = _node(program)
    assert result["status"] == result["cameraPage"]["status"] == "failed"
    assert result["cameraPage"]["phases"][0]["evidence"] == {"viewMode": "split"}
    assert result["cameraPage"]["cleanup"]["errors"] == [{"errorName": "FrameRemainsConnected"}]


def _source_scope() -> str:
    return r'''
const location=new URL('http://scout.test/admin/dashboard?projectId=project-a');
let selectedApi=''; const apiBase=()=>selectedApi,projectId=()=> 'project-a';
const asArray=value=>Array.isArray(value)?value:[];
const diagnosticRequire=(value,message)=>{if(!value)throw Error(message);};
const makeHypothesis=id=>({selection_id:id,provenance:{cache_key:id+'-sha'},corridor:{overlays:[5,10,20].map(size=>({
 mode:`top_${size}_percent_corridor`,sha256:id+'-'+size+'-sha',default_visible:size===10,
 runtime_href:`/admin/pretrip/projects/project-a/terrain-route-overlays/${id}-${size}.png`}))}});
const payload={project_id:'project-a',projection_compilation:{input_fingerprint:'projection-a'},terrain_raster_dem:{source_fingerprint:'dem-a'},
 terrain_route_hypothesis:{selection:{default_id:'hypothesis-a',options:['hypothesis-a','hypothesis-b'].map(makeHypothesis)}}};
const state={navigationTerrainData:payload,navigationTerrainHypothesisId:'hypothesis-b',navigationTerrainHypothesisBand:'top_20_percent_corridor'};
const navigationTerrainSnapshot=()=>state.navigationTerrainData||{project_id:'project-a'};
const navigationTerrainRouteHypothesisOptions=snapshot=>snapshot?.terrain_route_hypothesis?.selection?.options||[];
const navigationTerrainRouteHypothesisSelectionId=snapshot=>navigationTerrainRouteHypothesisOptions(snapshot)
 .find(option=>option.selection_id===state.navigationTerrainHypothesisId)?.selection_id||snapshot?.terrain_route_hypothesis?.selection?.default_id||'';
const navigationTerrainRouteHypothesisOverlay=(snapshot,band)=>navigationTerrainRouteHypothesisOptions(snapshot)
 .find(option=>option.selection_id===navigationTerrainRouteHypothesisSelectionId(snapshot))?.corridor.overlays.find(overlay=>overlay.mode===band)||null;
const navigationTerrainRouteHypothesisBand=snapshot=>navigationTerrainRouteHypothesisOverlay(snapshot,state.navigationTerrainHypothesisBand)
 ?state.navigationTerrainHypothesisBand:navigationTerrainRouteHypothesisOptions(snapshot).find(option=>option.selection_id===navigationTerrainRouteHypothesisSelectionId(snapshot))
 ?.corridor.overlays.find(overlay=>overlay.default_visible)?.mode||'';
const navigationTerrainRouteHypothesisImageSource=(snapshot,band)=>{
 const overlay=navigationTerrainRouteHypothesisOverlay(snapshot,band);return overlay?{type:'image',url:overlay.runtime_href+'?v='+overlay.sha256}:null;
};
''' + _functions("diagnosticNavigationScopeKey", "diagnosticNavigationCameraApiSource",
                 "diagnosticNavigationCameraSourceIdentity", "diagnosticNavigationCameraSourceContext",
                 "diagnosticNavigationCameraResolveSource", "diagnosticNavigationCameraVerifySource")


@pytest.mark.parametrize("api", ["http://other-runtime.test", "http://scout.test/proxy", "http://scout.test/?alternate=1"])
def test_d038_rejects_wrong_api_before_creating_any_iframe(api: str) -> None:
    program = _source_scope() + _functions("diagnosticNavigationCameraWholePage")
    program += "selectedApi=" + json.dumps(api) + ";\n"
    program += r'''
let framesCreated=0; const document={createElement:()=>{framesCreated++;throw Error('unexpected iframe');}};
diagnosticNavigationCameraWholePage().then(()=>{throw Error('unexpected success');},error=>console.log(JSON.stringify({framesCreated,failure:error.message})));
'''
    result = _node(program)
    assert result["framesCreated"] == 0
    assert "different API origin or path" in result["failure"]


def test_selected_parent_hypothesis_band_and_fingerprints_are_preserved() -> None:
    result = _node(_source_scope() + r'''
const context=diagnosticNavigationCameraSourceContext();
state.navigationTerrainHypothesisId='';state.navigationTerrainHypothesisBand='';
const receipt=diagnosticNavigationCameraResolveSource(context);
const evidence={sourceIdentity:diagnosticNavigationCameraSourceIdentity(),renderers:['2d','3d'].map(mode=>({mode,rasterSources:[
 {id:receipt.corridorSourceId,type:'image',url:receipt.corridorUrl}]}))};
diagnosticNavigationCameraVerifySource(evidence,receipt);
console.log(JSON.stringify({context,receipt,evidence}));
''')
    assert result["receipt"]["selectionId"] == "hypothesis-b"
    assert result["receipt"]["band"] == "top_20_percent_corridor"
    assert result["receipt"]["fingerprints"]["hypothesis"] == "hypothesis-b-sha"
    assert result["receipt"]["selectionSource"] == "parent-state"
    assert result["context"]["unavailableParentFingerprints"] == []


@pytest.mark.parametrize("mutation,expected", [
    ("context.api.origin='http://other-runtime.test';", "API does not match"),
    ("payload.terrain_route_hypothesis.selection.options=payload.terrain_route_hypothesis.selection.options.filter(option=>option.selection_id!=='hypothesis-b');", "hypothesis is unavailable"),
    ("context.band='top_30_percent_corridor';", "corridor band is unavailable"),
    ("payload.projection_compilation.input_fingerprint='projection-new';", "projection source identity"),
    ("payload.terrain_raster_dem.source_fingerprint='dem-new';", "dem source identity"),
    ("payload.terrain_route_hypothesis.selection.options[1].provenance.cache_key='new-cache';", "hypothesis source identity"),
    ("payload.terrain_route_hypothesis.selection.options[1].corridor.overlays[2].sha256='new-image';", "corridor source identity"),
])
def test_child_rejects_wrong_api_selection_band_or_source_identity(mutation: str, expected: str) -> None:
    result = _node(_source_scope() + "const context=diagnosticNavigationCameraSourceContext();\n" + mutation + r'''
let failure=null;try{diagnosticNavigationCameraResolveSource(context);}catch(error){failure=error.message;}
console.log(JSON.stringify({failure}));
''')
    assert expected in result["failure"]


@pytest.mark.parametrize("mutation,expected", [
    ("state.navigationTerrainHypothesisId='missing';", "parent selection is unavailable"),
    ("state.navigationTerrainHypothesisBand='top_30_percent_corridor';", "parent corridor band is unavailable"),
])
def test_parent_existing_ui_fallback_does_not_authorize_testing_another_selection(mutation: str, expected: str) -> None:
    result = _node(_source_scope() + mutation + r'''
let failure=null;try{diagnosticNavigationCameraSourceContext();}catch(error){failure=error.message;}
console.log(JSON.stringify({failure}));
''')
    assert expected in result["failure"]


def test_unloaded_parent_records_fresh_declared_default_without_claiming_parent_fingerprints() -> None:
    result = _node(_source_scope() + r'''
state.navigationTerrainData=null;state.navigationTerrainHypothesisId='';state.navigationTerrainHypothesisBand='';
const context=diagnosticNavigationCameraSourceContext();
state.navigationTerrainData=payload;
const receipt=diagnosticNavigationCameraResolveSource(context);
console.log(JSON.stringify({context,receipt}));
''')
    assert result["context"]["parentLoaded"] is False
    assert result["context"]["parentIdentity"] is None
    assert result["context"]["selectionId"] == ""
    assert len(result["context"]["unavailableParentFingerprints"]) == 4
    assert result["receipt"]["selectionId"] == "hypothesis-a"
    assert result["receipt"]["selectionSource"] == "fresh-payload-declared-default"
    assert result["receipt"]["bandSource"] == "fresh-payload-declared-default"


def test_missing_declared_default_cannot_substitute_first_available_option() -> None:
    result = _node(_source_scope() + r'''
state.navigationTerrainData=null;state.navigationTerrainHypothesisId='';state.navigationTerrainHypothesisBand='';
const context=diagnosticNavigationCameraSourceContext();state.navigationTerrainData=payload;
payload.terrain_route_hypothesis.selection.default_id='';
let failure=null;try{diagnosticNavigationCameraResolveSource(context);}catch(error){failure=error.message;}
console.log(JSON.stringify({failure}));
''')
    assert "fallback substitution is forbidden" in result["failure"]


@pytest.mark.parametrize("mutation,expected", [
    ("evidence.sourceIdentity.selectionId='hypothesis-a';", "hypothesis selection changed"),
    ("evidence.sourceIdentity.requestedBand='top_10_percent_corridor';", "corridor band changed"),
    ("evidence.sourceIdentity.fingerprints.dem='another-dem';", "source identity changed"),
    ("evidence.renderers[0].rasterSources[0].url='/another-hypothesis.png';", "actual corridor source"),
])
def test_each_phase_rejects_source_drift_or_stale_actual_corridor(mutation: str, expected: str) -> None:
    result = _node(_source_scope() + r'''
const receipt=diagnosticNavigationCameraResolveSource(diagnosticNavigationCameraSourceContext());
const evidence={sourceIdentity:diagnosticNavigationCameraSourceIdentity(),renderers:[{mode:'3d',rasterSources:[
 {id:receipt.corridorSourceId,type:'image',url:receipt.corridorUrl}]}]};
''' + mutation + r'''
let failure=null;try{diagnosticNavigationCameraVerifySource(evidence,receipt);}catch(error){failure=error.message;}
console.log(JSON.stringify({failure}));
''')
    assert expected in result["failure"]


@pytest.mark.parametrize("scenario", ["empty", "generation-invalidated", "module-rejected", "snapshot-threw"])
def test_shared_initializer_tracker_settles_actual_early_returns_and_failures(scenario: str) -> None:
    program = r'''
const scenario=SCENARIO;
const runtime={generation:1,maps:[],pendingInitializations:new Set(),initializationStarted:0,initializationSettled:0};
const navigationTerrainMapLibreRuntime=runtime,state={route:'outdoor-navigation'};
const host={dataset:{},parentElement:{querySelector:()=>null}};
const document={querySelectorAll:()=>scenario==='empty'?[]:[host]};
const navigationTerrainSnapshot=()=>{if(scenario==='snapshot-threw')throw Error('snapshot failed');return {};};
const navigationTerrainRouteDemCoverageText=()=>'',navigationTerrainInterpolationText=()=>'',navigationTerrainDemReady=()=>true;
const navigationTerrainMapLibreFeatureCollection=()=>({}),navigationTerrainMapLibreVisibilitySummary=()=>({}),navigationTerrainMapLibreLensSummary=()=>({});
let release,reject;
const modulePromise=new Promise((resolve,fail)=>{release=resolve;reject=fail;});
const loadNavigationTerrainMapLibre=()=>modulePromise;
'''.replace("SCENARIO", json.dumps(scenario))
    program += _functions("initializeNavigationTerrainMapLibre")
    program += r'''
(async()=>{
 let failure=null;
 const initialization=initializeNavigationTerrainMapLibre().catch(error=>{failure=error.message;});
 const during={pending:runtime.pendingInitializations.size,started:runtime.initializationStarted,settled:runtime.initializationSettled};
 const latches=[...runtime.pendingInitializations];
 if(scenario==='generation-invalidated'){runtime.generation++;release({});}
 if(scenario==='module-rejected')reject(Error('module unavailable'));
 await initialization;await Promise.allSettled(latches);
 console.log(JSON.stringify({during,pending:runtime.pendingInitializations.size,started:runtime.initializationStarted,
 settled:runtime.initializationSettled,hostStatus:host.dataset.navigationMaplibreStatus,failure}));
})().catch(error=>{console.error(error);process.exit(1);});
'''
    result = _node(program)
    assert result["pending"] == 0 and result["started"] == result["settled"] == 1
    if scenario in {"generation-invalidated", "module-rejected"}:
        assert result["during"] == {"pending": 1, "started": 1, "settled": 0}
    if scenario == "module-rejected":
        assert result["hostStatus"] == "failed"
    if scenario == "snapshot-threw":
        assert result["failure"] == "snapshot failed"
